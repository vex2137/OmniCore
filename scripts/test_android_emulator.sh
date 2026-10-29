#!/usr/bin/env bash
# Execute in one shell: android-emulator-runner runs each script line independently.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir/apps/android"
adb shell getconf PAGE_SIZE
adb shell mkdir -p /sdcard/Download
test_status=0
./gradlew --no-daemon connectedDebugAndroidTest || test_status=$?
mkdir -p "$repo_dir/dist/android-evidence"
adb pull /sdcard/Download/omnicore-android-chat.png "$repo_dir/dist/android-evidence/android-chat.png" || true
adb pull /sdcard/Download/omnicore-android-failure.png "$repo_dir/dist/android-evidence/android-failure.png" || true
exit "$test_status"
