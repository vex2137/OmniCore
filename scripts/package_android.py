"""Stage and verify ARM64 APKs, 16 KiB page alignment, metadata, and SHA-256 checksums."""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION = json.loads((ROOT / "backend/src/omnicore/distribution.json").read_text())
VERSION = DISTRIBUTION["version"]


def verify_apk(sdk: Path, apk: Path, *, require_signature: bool) -> tuple[str, bool]:
    """Verify 16 KiB ZIP/ELF alignment, manifest identity, and optional signature."""
    subprocess.run([str(sdk / "zipalign"), "-c", "-P", "16", "4", str(apk)], check=True)  # noqa: S603
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if not name.endswith(".so"):
                continue
            binary = archive.read(name)
            assert binary[:6] == b"\x7fELF\x02\x01", name
            offset = struct.unpack_from("<Q", binary, 32)[0]
            stride, count = struct.unpack_from("<HH", binary, 54)
            for index in range(count):
                position = offset + index * stride
                if struct.unpack_from("<I", binary, position)[0] == 1:
                    assert struct.unpack_from("<Q", binary, position + 48)[0] >= 16384, name
    signed = (
        subprocess.run(  # noqa: S603
            [str(sdk / "apksigner"), "verify", str(apk)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )
    if require_signature and not signed:
        raise SystemExit(f"Expected valid APK signature on {apk}")
    metadata = subprocess.check_output(  # noqa: S603
        [str(sdk / "aapt"), "dump", "badging", str(apk)], text=True
    )
    assert f"name='{DISTRIBUTION['android_application_id']}'" in metadata
    assert f"versionName='{VERSION}'" in metadata
    assert f"versionCode='{DISTRIBUTION['android_version_code']}'" in metadata
    assert "targetSdkVersion:'36'" in metadata
    assert "sdkVersion:'26'" in metadata
    assert "native-code: 'arm64-v8a'" in metadata
    with apk.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest(), signed


def main():
    sdk = Path(os.environ["ANDROID_HOME"]) / "build-tools/36.0.0"
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    source_commit = subprocess.check_output(  # noqa: S603,S607 — local Git metadata.
        [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()

    debug_apk = ROOT / "apps/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
    if not debug_apk.is_file():
        raise SystemExit("Build apps/android :app:assembleDebug before packaging")
    debug_sha, _ = verify_apk(sdk, debug_apk, require_signature=True)
    debug_target = output / f"OmniCore-{VERSION}-android-arm64.apk"
    shutil.copy2(debug_apk, debug_target)
    debug_target.with_suffix(".apk.sha256").write_text(f"{debug_sha}  {debug_target.name}\n")

    release_signed = ROOT / "apps/android/app/build/outputs/apk/release/app-arm64-v8a-release.apk"
    release_unsigned = (
        ROOT / "apps/android/app/build/outputs/apk/release/app-arm64-v8a-release-unsigned.apk"
    )
    release_info = None
    if release_signed.is_file():
        rel_sha, is_signed = verify_apk(sdk, release_signed, require_signature=True)
        rel_target = output / f"OmniCore-{VERSION}-android-arm64-release.apk"
        shutil.copy2(release_signed, rel_target)
        rel_target.with_suffix(".apk.sha256").write_text(f"{rel_sha}  {rel_target.name}\n")
        release_info = {
            "filename": rel_target.name,
            "sha256": rel_sha,
            "signed": is_signed,
            "build_type": "release, keystore-signed",
        }
    elif release_unsigned.is_file():
        rel_sha, _ = verify_apk(sdk, release_unsigned, require_signature=False)
        rel_target = output / f"OmniCore-{VERSION}-android-arm64-release-unsigned.apk"
        shutil.copy2(release_unsigned, rel_target)
        rel_target.with_suffix(".apk.sha256").write_text(f"{rel_sha}  {rel_target.name}\n")
        release_info = {
            "filename": rel_target.name,
            "sha256": rel_sha,
            "signed": False,
            "build_type": "release, unsigned (no production keystore configured)",
        }

    (output / "android-build.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "version_code": DISTRIBUTION["android_version_code"],
                "application_id": DISTRIBUTION["android_application_id"],
                "build_type": "debug, test signing key; not a production signature",
                "abi": "arm64-v8a",
                "min_sdk": 26,
                "target_sdk": 36,
                "sha256": debug_sha,
                "release_apk": release_info,
                "source_commit": source_commit,
                "inference_on_phone": False,
                "native_page_alignment_bytes": 16384,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Verified and staged {debug_target}\nSHA256 {debug_sha}")
    if release_info:
        rel_path = output / release_info["filename"]
        print(f"Verified and staged {rel_path}\nSHA256 {release_info['sha256']}")


if __name__ == "__main__":
    main()
