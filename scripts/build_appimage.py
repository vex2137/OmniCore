"""Build an offline-capable native client. No weights or secrets are packaged."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "/usr/bin/git"
NAME = "OmniCore-0.1.0-alpha-x86_64.AppImage"


def run(*command, **kwargs):
    subprocess.run(command, check=True, **kwargs)  # noqa: S603 — explicit build tools, no shell.


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_licenses(target):
    target.mkdir(parents=True)
    shutil.copy2(ROOT / "LICENSE", target / "OmniCore-MIT.txt")
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            if any(key in str(file).lower() for key in ("license", "copyright", "copying")):
                source = Path(distribution.locate_file(file))
                if source.is_file() and ".." not in file.parts:
                    destination = target / distribution.metadata["Name"] / file
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    for candidate in (
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "lib/python3.12/LICENSE.txt",
    ):
        if candidate.is_file():
            shutil.copy2(candidate, target / "Python-LICENSE.txt")
            break
    for package in ("libssl3t64", "libstdc++6", "libgcc-s1", "zlib1g", "libzstd1"):
        source = Path("/usr/share/doc") / package / "copyright"
        if source.is_file():
            shutil.copy2(source, target / f"{package}-copyright.txt")
    (target / "SOURCES.md").write_text(
        "# Third-party source and replacement\n\n"
        "Qt/PySide6 6.8.3 and shiboken6 use LGPL/GPL/commercial terms; licenses are included.\n"
        "Official source: https://code.qt.io/cgit/pyside/pyside-setup.git/ (v6.8.3); "
        "https://download.qt.io/archive/qt/6.8/6.8.3/ .\n"
        "Libraries remain dynamically linked. Extract with --appimage-extract, replace libraries "
        "in usr/bin/_internal/PySide6, then run AppRun. This is not a restriction on relinking.\n"
        "AppImage runtime source: https://github.com/AppImage/type2-runtime "
        "(MIT plus statically linked libraries); "
        "runtime digest is recorded in build-manifest.json.\n"
        "llama.cpp source/license, when included, is recorded alongside its executable. "
        "No model weights or model licenses are implied by the application license.\n"
    )


def bundle_engine(executable, destination, patchelf):
    if not executable:
        return None
    executable = executable.resolve(strict=True)
    destination.mkdir()
    shutil.copy2(executable, destination / "llama-server")
    output = subprocess.check_output(["ldd", str(executable)], text=True)  # noqa: S603,S607
    if "not found" in output:
        raise RuntimeError("Engine has unresolved libraries")
    dependencies = re.findall(r"=> (/\S+)", output)
    for name in dependencies:
        source = Path(name)
        if source.name in {"libc.so.6", "libm.so.6"}:
            continue  # Use the host glibc and ELF loader, as AppImages require.
        shutil.copy2(source.resolve(), destination / source.name)
    for path in destination.iterdir():
        run(patchelf, "--set-rpath", "$ORIGIN", str(path))
        path.chmod(0o755)
    license_path = executable.parents[2] / "LICENSE"
    if not license_path.is_file():
        raise RuntimeError("Provide a source build with the llama.cpp LICENSE available")
    shutil.copy2(license_path, destination / "LICENSE")
    commit = subprocess.check_output(  # noqa: S603,S607 — metadata only.
        [GIT, "-C", str(executable.parents[2]), "rev-parse", "HEAD"],
        text=True,  # noqa: S607
    ).strip()
    return {
        "source": "https://github.com/ggml-org/llama.cpp",
        "commit": commit,
        "input_sha256": digest(executable),
        "packaged_sha256": digest(destination / "llama-server"),
        "acceleration": "CPU only; no CUDA claim",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--llama-server", type=Path)
    parser.add_argument("--mksquashfs", default=shutil.which("mksquashfs"))
    parser.add_argument("--patchelf", default=shutil.which("patchelf"))
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if platform.machine() != "x86_64" or sys.platform != "linux":
        parser.error("Linux x86_64 is required")
    if not args.mksquashfs or (args.llama_server and not args.patchelf):
        parser.error("Install squashfs-tools and patchelf for CPU engine bundling")
    build = ROOT / "build" / "appimage"
    if build.exists():
        shutil.rmtree(build)  # Only this script's disposable build output.
    build.mkdir(parents=True)
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((ROOT / "packaging/linux/runtime.json").read_text())
    runtime = args.runtime
    if runtime is None:
        runtime = build / "runtime-x86_64"
        urllib.request.urlretrieve(metadata["url"], runtime)  # noqa: S310 — pinned HTTPS + digest.
    if digest(runtime) != metadata["sha256"]:
        raise RuntimeError(
            "AppImage runtime checksum mismatch; review official release before updating"
        )
    appdir = build / "OmniCore.AppDir"
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "OmniCore",
        "--distpath",
        str(build / "frozen"),
        "--workpath",
        str(build / "pyinstaller"),
        "--specpath",
        str(build),
        "--collect-all",
        "omnicore",
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "websockets.legacy.server",
        "--hidden-import",
        "sqlite3",
        "--exclude-module",
        "PySide6.QtQml",
        "--exclude-module",
        "PySide6.QtQuick",
        str(ROOT / "packaging/linux/entrypoint.py"),
        cwd=ROOT,
    )
    binary_dir = appdir / "usr/bin"
    binary_dir.mkdir(parents=True)
    shutil.copytree(build / "frozen/OmniCore", binary_dir, dirs_exist_ok=True)
    shutil.copy2(ROOT / "packaging/linux/AppRun", appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)
    shutil.copy2(ROOT / "packaging/linux/io.github.vex2137.OmniCore.desktop", appdir)
    icon = ROOT / "backend/src/omnicore/desktop/icon.svg"
    shutil.copy2(icon, appdir / "io.github.vex2137.OmniCore.svg")
    (appdir / ".DirIcon").symlink_to("io.github.vex2137.OmniCore.svg")
    licenses = appdir / "usr/share/licenses/OmniCore"
    copy_licenses(licenses)
    shutil.copy2(ROOT / "packaging/linux/appimage-runtime-LICENSE", licenses)
    engine = bundle_engine(args.llama_server, binary_dir / "engines", args.patchelf)
    manifest = {
        "version": "0.1.0-alpha.1",
        "python": platform.python_version(),
        "build_platform": platform.platform(),
        "glibc_build_host": platform.libc_ver(),
        "source_commit": subprocess.check_output(  # noqa: S603 — local Git metadata.
            [GIT, "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,  # noqa: S607
        ).strip(),  # noqa: S603,S607
        "runtime": metadata,
        "engine": engine,
        "model_weights": False,
    }
    (appdir / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    squash = build / "filesystem.squashfs"
    run(
        args.mksquashfs,
        str(appdir),
        str(squash),
        "-noappend",
        "-all-root",
        "-comp",
        "gzip",
        "-processors",
        str(min(os.cpu_count() or 1, 2)),
        "-no-xattrs",
    )
    image = args.output / NAME
    with image.open("wb") as output:
        for source in (runtime, squash):
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, output)
    image.chmod(0o755)
    checksum = digest(image)
    image.with_suffix(image.suffix + ".sha256").write_text(f"{checksum}  {image.name}\n")
    (args.output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {image}\nSHA256 {checksum}")


if __name__ == "__main__":
    main()
