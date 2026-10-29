"""Stage the actual debug-signed ARM64 APK and verify its identity/signature."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sdk = Path(os.environ["ANDROID_HOME"]) / "build-tools/35.0.0"
    apk = ROOT / "apps/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
    if not apk.is_file():
        raise SystemExit("Build apps/android :app:assembleDebug before packaging")
    subprocess.run([str(sdk / "apksigner"), "verify", str(apk)], check=True)  # noqa: S603
    metadata = subprocess.check_output(  # noqa: S603
        [str(sdk / "aapt"), "dump", "badging", str(apk)], text=True
    )
    assert "name='io.github.vex2137.omnicore'" in metadata
    assert "versionName='0.1.0-alpha.1'" in metadata
    assert "sdkVersion:'26'" in metadata
    assert "native-code: 'arm64-v8a'" in metadata
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    target = output / "OmniCore-0.1.0-alpha-android-arm64.apk"
    shutil.copy2(apk, target)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    target.with_suffix(".apk.sha256").write_text(f"{digest}  {target.name}\n")
    (output / "android-build.json").write_text(
        json.dumps(
            {
                "version": "0.1.0-alpha.1",
                "application_id": "io.github.vex2137.omnicore",
                "build_type": "debug, test signing key; not a production signature",
                "abi": "arm64-v8a",
                "min_sdk": 26,
                "target_sdk": 35,
                "sha256": digest,
                "source_commit": subprocess.check_output(  # noqa: S603,S607 — local Git metadata.
                    [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    text=True,
                ).strip(),
                "inference_on_phone": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Verified and staged {target}\nSHA256 {digest}")


if __name__ == "__main__":
    main()
