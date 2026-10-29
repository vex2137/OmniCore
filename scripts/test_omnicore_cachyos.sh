#!/usr/bin/env bash
# Read-only model references; isolated disposable catalog, reports contain no tokens.
set -euo pipefail
if (( $# < 2 )); then
  echo 'Usage: bash test_omnicore_cachyos.sh /path/OmniCore.AppImage /path/LFM3.gguf [/path/Qwen.gguf]' >&2
  exit 2
fi
omnicore_image=$(realpath -- "$1")
shift
test -x "$omnicore_image" || { echo 'Make the downloaded AppImage executable first (chmod +x).' >&2; exit 2; }
omnicore_arguments=()
for model_path in "$@"; do
  test -f "$model_path"
  omnicore_arguments+=(--model "$(realpath -- "$model_path")")
done
# No sudo, no existing database, no secrets in arguments or output.
APPIMAGE_EXTRACT_AND_RUN=1 "$omnicore_image" --hardware-test "${omnicore_arguments[@]}"
