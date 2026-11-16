"""Build the pinned llama.cpp Android arm64 CPU/Vulkan server binary (no weights).

Requires Android NDK 29.0.14206865 and CMake 3.31.6 (installed via sdkmanager),
plus host g++/make. Downloads are SHA-256 verified before extraction.
Outputs ``libomnicore_llama.so`` into ``apps/android/app/src/main/jniLibs/arm64-v8a/``.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_APP = ROOT / "apps" / "android" / "app" / "src" / "main"
LLAMA_COMMIT = "620d2225cc436ab0b001e3200e590e3b286ef9ab"
SOURCES = [
    (
        "llama-src",
        f"https://codeload.github.com/ggml-org/llama.cpp/tar.gz/{LLAMA_COMMIT}",
        "1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9",
    ),
    (
        "spirv-headers",
        "https://codeload.github.com/KhronosGroup/SPIRV-Headers/tar.gz/vulkan-sdk-1.4.313.0",
        "f68be549d74afb61600a1e3a7d1da1e6b7437758c8e77d664909f88f302c5ac1",
    ),
    (
        "vulkan-headers",
        "https://codeload.github.com/KhronosGroup/Vulkan-Headers/tar.gz/vulkan-sdk-1.4.335.0",
        "269e95cc5138ea0a0d52fcb0ee19102add2560fedf5a43b1b5c17780c2775764",
    ),
]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(cmake_bin: Path, *command):
    env = {**os.environ, "PATH": f"{cmake_bin.parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    subprocess.run([str(x) for x in command], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk", default=os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    )
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if not args.sdk:
        parser.error("--sdk or ANDROID_SDK_ROOT is required")

    sdk = Path(args.sdk).resolve()
    cmake = sdk / "cmake/3.31.6/bin/cmake"
    ndk = sdk / "ndk/29.0.14206865"
    if not cmake.is_file() or not ndk.is_dir():
        raise SystemExit("Install ndk;29.0.14206865 and cmake;3.31.6 with sdkmanager first")

    work = ROOT / "build" / "android-native"
    work.mkdir(parents=True, exist_ok=True)

    for name, url, expected in SOURCES:
        archive = work / f"{name}.tar.gz"
        source = work / name
        if not archive.exists() or sha256(archive) != expected:
            partial = archive.with_suffix(".partial")
            run(
                cmake,
                "curl",
                "--fail",
                "--location",
                "--retry",
                "2",
                "--max-time",
                "180",
                "--output",
                partial,
                url,
            )
            if sha256(partial) != expected:
                raise SystemExit(f"Source checksum mismatch: {name}")
            partial.replace(archive)
        if not source.exists():
            source.mkdir()
            with tarfile.open(archive) as tar:
                for member in tar.getmembers():
                    parts = Path(member.name).parts[1:]
                    if not parts:
                        continue
                    member.name = str(Path(*parts))
                    tar.extract(member, source, filter="data")

    # Upstream omits SPIRV-Headers include target on Android.
    cm = work / "llama-src/ggml/src/ggml-vulkan/CMakeLists.txt"
    cm_text = cm.read_text()
    if "SPIRV-Headers::SPIRV-Headers" not in cm_text:
        cm.write_text(
            cm_text.replace(
                "PRIVATE Vulkan::Vulkan)", "PRIVATE Vulkan::Vulkan SPIRV-Headers::SPIRV-Headers)"
            )
        )

    run(
        cmake,
        cmake,
        "-S",
        work / "spirv-headers",
        "-B",
        work / "spirv-host",
        f"-DCMAKE_INSTALL_PREFIX={work}/spirv-install",
        "-DSPIRV_HEADERS_ENABLE_TESTS=OFF",
    )
    run(cmake, cmake, "--install", work / "spirv-host")
    run(
        cmake,
        cmake,
        "-S",
        work / "llama-src",
        "-B",
        work / "llama-android-arm64",
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={cmake.parent}/ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake",
        "-DANDROID_ABI=arm64-v8a",
        "-DANDROID_PLATFORM=android-28",
        "-DANDROID_STL=c++_static",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DGGML_OPENMP=OFF",
        "-DGGML_VULKAN=ON",
        "-DGGML_NATIVE=OFF",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_BUILD_EXAMPLES=OFF",
        "-DLLAMA_BUILD_TOOLS=ON",
        "-DLLAMA_BUILD_SERVER=ON",
        "-DLLAMA_OPENSSL=OFF",
        "-DLLAMA_CURL=OFF",
        "-DLLAMA_SERVER_WEBUI=OFF",
        "-DLLAMA_BUILD_NUMBER=11669",
        f"-DLLAMA_BUILD_COMMIT={LLAMA_COMMIT}",
        f"-DVulkan_GLSLC_EXECUTABLE={ndk}/shader-tools/linux-x86_64/glslc",
        f"-DVulkan_INCLUDE_DIR={work}/vulkan-headers/include",
        f"-DSPIRV-Headers_DIR={work}/spirv-install/share/cmake/SPIRV-Headers",
    )
    run(
        cmake,
        cmake,
        "--build",
        work / "llama-android-arm64",
        "--target",
        "llama-server",
        "-j",
        str(max(1, min(args.jobs, 8))),
    )

    jni_dir = ANDROID_APP / "jniLibs" / "arm64-v8a"
    jni_dir.mkdir(parents=True, exist_ok=True)
    target_bin = jni_dir / "libomnicore_llama.so"
    shutil.copyfile(work / "llama-android-arm64/bin/llama-server", target_bin)
    run(
        cmake,
        ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip",
        "--strip-unneeded",
        target_bin,
    )

    assets = ANDROID_APP / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    manifest = {
        "llamaCommit": LLAMA_COMMIT,
        "llamaVersion": "b11669",
        "abi": "arm64-v8a",
        "minApi": 28,
        "ndk": "29.0.14206865",
        "vulkan": True,
        "binarySha256": sha256(target_bin),
        "sources": [{"url": url, "sha256": digest} for _, url, digest in SOURCES],
    }
    (assets / "android-native-runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
