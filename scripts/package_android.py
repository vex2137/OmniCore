"""Stage the actual debug-signed ARM64 APK and verify its identity/signature."""

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


def main():
    sdk = Path(os.environ["ANDROID_HOME"]) / "build-tools/36.0.0"
    apk = ROOT / "apps/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
    if not apk.is_file():
        raise SystemExit("Build apps/android :app:assembleDebug before packaging")
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
    assert f"name='{DISTRIBUTION['android_application_id']}'" in metadata
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
                "application_id": DISTRIBUTION["android_application_id"],
                "build_type": "debug, test signing key; not a production signature",
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
