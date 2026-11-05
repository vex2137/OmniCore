"""Verify APK identity with Android SDK tools; never read a private keystore."""

import os
import re
import subprocess
from pathlib import Path


def apk_identity(apk: Path, sdk: Path) -> dict:
    certificate = subprocess.check_output(  # noqa: S603
        [str(sdk / "apksigner"), "verify", "--print-certs", str(apk)],
        text=True,
        timeout=60,
    )
    signers = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]{64})", certificate)
    if len(signers) != 1:
        raise ValueError("Exactly one verified signing certificate is required")
    badging = subprocess.check_output(  # noqa: S603
        [str(sdk / "aapt"), "dump", "badging", str(apk)], text=True, timeout=30
    )
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)'", badging)
    if not package:
        raise ValueError("Invalid APK package metadata")
    return {
        "application_id": package[1],
        "version_code": int(package[2]),
        "certificate_sha256": signers[0].lower(),
        "debug_key": "CN=Android Debug" in certificate,
        "debuggable": "application-debuggable" in badging,
    }


def verify_release(identity: dict, expected_certificate: str, expected_id: str):
    fingerprint = expected_certificate.replace(":", "").lower()
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint) or not expected_id:
        raise ValueError("Release certificate pin and application ID are required")
    if identity["debug_key"] or identity["debuggable"]:
        raise ValueError("Debug signing/build is not accepted as a release")
    if identity["certificate_sha256"] != fingerprint or identity["application_id"] != expected_id:
        raise ValueError("Release signing identity does not match the pinned owner configuration")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Check APK update identity without changing device data"
    )
    parser.add_argument("previous", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    sdk = Path(os.environ["ANDROID_HOME"]) / "build-tools/36.0.0"
    previous, candidate = (apk_identity(p, sdk) for p in (args.previous, args.candidate))
    for field in ("application_id", "certificate_sha256"):
        if previous[field] != candidate[field]:
            parser.exit(1, f"Update refused: incompatible {field}. No device data changed.\n")
    if candidate["version_code"] <= previous["version_code"]:
        parser.exit(1, "Update refused: versionCode must increase. No device data changed.\n")
    print("Update identity compatible. Device data/Keystore still require an installation test.")


if __name__ == "__main__":
    main()
