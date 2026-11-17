# OmniCore 1.0.0 Release Notes & Deployment Guide

## Highlights

### Android (`1.0.0`, `versionCode: 11`)
- **Compact Message Statistics Footer:** Replaced inline wall-of-text statistics below assistant replies with a compact summary (`13.4 tok/s · 11.63 s · Details` / `Szczegóły`) and an accessible toggle that expands the full inference metrics panel (speed, input/output tokens, TTFT, first answer latency, elapsed time, model load time, context usage, finish reason, GPU layers, device, CPU fallback).
- **Cancellation & Streaming Polish:** Statistics remain hidden while actively streaming and preserve partial output and elapsed/rate metrics cleanly upon cancellation.
- **GGUF & Engine Reliability (from Beta 4):** Pinned `llama.cpp` runtime (`c3df4b7e`) supporting `lfm3` and `qwen35`, bounded structural GGUF v2/v3 header/tensor validation, Vulkan capability/offload reporting without reporting shared system RAM as VRAM, and clean release branding (`OmniCore`).

### Linux Desktop & Backend (`1.0.0`)
- **Agent Tool-Use Fix:** Updated the Agent system prompt to respond naturally to greetings, capability questions, and general knowledge without calling tools, and omitted filesystem tools when no folders are granted and no file/folder intent is present (verified on `LFM3 1.7B` and `Qwen3.5 4B`).
- **Message Bubble Sizing:** Fixed premature wrapping of short user bubbles by re-measuring `SafeMarkdown` after Qt stylesheet polish and dynamically adapting bubble max width (~72% of chat viewport) on resize and inspector drawer toggle.
- **Checkbox Theme Fix:** Fixed black rectangular background inheritance on Settings checkboxes (`Włącz opcjonalną integrację z Ollamą`, `Myślenie (tylko zgodne szablony modeli)`) across all 7 themes (`system`, `light`, `midnight`, `graphite`, `oled`, `ocean`, `forest`), with HiDPI checkmark indicators and crisp focus/hover/disabled states.
- **Responsive Scaling (80%–200%):** Wrapping `FlowLayout` toolbars/inspector actions, sidebar nav elision fallback, and compact resource pill thresholds.
- **CUDA & Memory Safety:** Restricted `_available_vram_bytes` strictly to `CUDA*` devices so unified/CPU systems never treat host RAM as GPU VRAM.

---

## Reproducible Build Instructions

### Linux x86_64 AppImage (with pinned `c3df4b7e` CPU `llama-server`)
```bash
uv sync --frozen --extra desktop --group gui-test --group packaging
git clone https://github.com/ggml-org/llama.cpp.git /tmp/llama-cpu
git -C /tmp/llama-cpu checkout --detach c3df4b7e22a1ac38da663552d19e649dd97ca936
cmake -S /tmp/llama-cpu -B /tmp/llama-cpu/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build /tmp/llama-cpu/build --target llama-server -j "$(nproc)"
.venv/bin/python scripts/build_appimage.py --llama-server /tmp/llama-cpu/build/bin/llama-server
```

### Android ARM64 APK
```bash
python3 scripts/build_android_native.py --sdk "$ANDROID_SDK_ROOT"
cd apps/android
./gradlew testDebugUnitTest lintDebug assembleDebug assembleRelease
cd ../..
python3 scripts/package_android.py
```

#### Production Release Signing
To produce a production-signed release APK without modifying source or committing secrets, export your release keystore environment variables before running `./gradlew assembleRelease`:
```bash
export OMNICORE_KEYSTORE_PATH=/path/to/release.keystore
export OMNICORE_KEY_ALIAS=omnicore
export OMNICORE_KEYSTORE_PASSWORD='...'
export OMNICORE_KEY_PASSWORD='...'
```
Debug-signed (`OmniCore-1.0.0-android-arm64.apk`) and unsigned release (`OmniCore-1.0.0-android-arm64-release-unsigned.apk`) artifacts are never production-signed.

---

## Installation & Upgrade from Beta 4

### Linux Desktop
```bash
chmod +x OmniCore-1.0.0-x86_64.AppImage
sha256sum -c OmniCore-1.0.0-x86_64.AppImage.sha256
./OmniCore-1.0.0-x86_64.AppImage
```
Existing configuration under `~/.config/omnicore/` and local models/history under `~/.local/share/omnicore/` are preserved automatically.

### Android
The `applicationId` remains `io.github.vex2137.omnicore.rc` with `versionCode` progressing from `10` (Beta 4) to `11` (`1.0.0`), allowing in-place upgrade over Beta 4 via a matching debug key (`adb install -r`) without losing imported `.gguf` files in `files/omnicore-models/` or local conversations.
