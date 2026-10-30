"""Stage a verified ARM64 APK; owner release signing is opt-in and pinned."""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

from android_identity import apk_identity, verify_release

ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION = json.loads((ROOT / "backend/src/omnicore/distribution.json").read_text())
VERSION = DISTRIBUTION["version"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    variant = "release" if args.release else "debug"
    sdk = Path(os.environ["ANDROID_HOME"]) / "build-tools/36.0.0"
    apk = ROOT / f"apps/android/app/build/outputs/apk/{variant}/app-arm64-v8a-{variant}.apk"
    if not apk.is_file():
        raise SystemExit(f"Build apps/android :app:assemble{variant.title()} before packaging")
    identity = apk_identity(apk, sdk)
    if args.release:
        verify_release(
            identity,
            os.environ.get("OMNICORE_ANDROID_CERT_SHA256", ""),
            os.environ.get("OMNICORE_ANDROID_RELEASE_ID", ""),
        )
    expected_id = (
        os.environ["OMNICORE_ANDROID_RELEASE_ID"]
        if args.release
        else DISTRIBUTION["android_application_id"]
    )
    # Android 15/16 devices may use 16 KiB pages. Check both ZIP and ELF alignment.
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
    subprocess.run([str(sdk / "apksigner"), "verify", str(apk)], check=True)  # noqa: S603
    metadata = subprocess.check_output(  # noqa: S603
        [str(sdk / "aapt"), "dump", "badging", str(apk)], text=True
    )
    assert f"name='{expected_id}'" in metadata
    assert f"versionName='{VERSION}'" in metadata
    assert f"versionCode='{DISTRIBUTION['android_version_code']}'" in metadata
    assert "targetSdkVersion:'36'" in metadata
    assert "sdkVersion:'26'" in metadata
    assert "native-code: 'arm64-v8a'" in metadata
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    target = output / f"OmniCore-{VERSION}-android-arm64.apk"
    shutil.copy2(apk, target)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    target.with_suffix(".apk.sha256").write_text(f"{digest}  {target.name}\n")
    (output / "android-build.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "application_id": expected_id,
                "build_type": "release, supplied owner identity; persistence requires owner backup"
                if args.release
                else "debug, test signing key; not a production signature",
                "certificate_sha256": identity["certificate_sha256"],
                "abi": "arm64-v8a",
                "min_sdk": 26,
                "target_sdk": 36,
                "sha256": digest,
                "source_commit": subprocess.check_output(  # noqa: S603,S607 — local Git metadata.
                    [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    text=True,
                ).strip(),
                "inference_on_phone": False,
                "native_page_alignment_bytes": 16384,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Verified and staged {target}\nSHA256 {digest}")


if __name__ == "__main__":
    main()
