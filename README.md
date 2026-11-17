
<div align="center">

# 🚀 OmniCore

### Your AI. Your Hardware. Your Control.

**Open-source local AI for Linux and Android.**

Run AI models on your own hardware, manage conversations, monitor inference performance, and explore local AI without relying on cloud subscriptions.

[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/vex2137/OmniCore/releases/tag/v1.0.0)
[![Release](https://img.shields.io/badge/release-stable-brightgreen)](https://github.com/vex2137/OmniCore/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Linux](https://img.shields.io/badge/Linux-x86__64-orange?logo=linux)](https://github.com/vex2137/OmniCore/releases)
[![Android](https://img.shields.io/badge/Android-ARM64-green?logo=android)](https://github.com/vex2137/OmniCore/releases)

**[Download](https://github.com/vex2137/OmniCore/releases/latest) · [Features](#-features) · [Installation](#-installation) · [Documentation](#-documentation)**

</div>

---

## 🌟 What is OmniCore?

**OmniCore** is a free and open-source application for running and interacting with AI models locally.

Built with a focus on performance, privacy, and usability, OmniCore provides a unified environment for local AI inference on desktop and mobile devices.

Instead of relying on remote AI services, supported models can run directly on your own hardware.

### Why OmniCore?

- 🧠 **Local AI** — Run compatible GGUF language models.
- 🔒 **Privacy** — Keep local inference on your own device.
- ⚡ **Performance** — Take advantage of supported GPU acceleration.
- 🤖 **AI Agent** — Use tools and advanced workflows on Linux.
- 🎨 **Modern UI** — Responsive interface with customizable themes.
- 📊 **Statistics** — Monitor generation speed, latency, and token usage.
- 🌍 **Multilingual** — Polish and English interface support.
- 💻 **Cross-platform** — Available for Linux and Android.
- ❤️ **Open source** — Licensed under MIT.

---

## 📥 Download

### Latest Stable Release: v1.0.0

| Platform | Architecture | Download |
|---|---|---|
| 🐧 Linux | x86_64 | [Download AppImage](https://github.com/vex2137/OmniCore/releases/download/v1.0.0/OmniCore-1.0.0-x86_64.AppImage) |
| 🤖 Android | ARM64 | [Download APK](https://github.com/vex2137/OmniCore/releases/download/v1.0.0/OmniCore-1.0.0-android-arm64-release.apk) |

**[View all releases](https://github.com/vex2137/OmniCore/releases)**

> OmniCore 1.0.0 is the first official stable release.

---

## ✨ Features

### 🧠 Local AI Inference

Run compatible GGUF language models locally using llama.cpp.

- Support for LFM3 and Qwen model families.
- Real-time token streaming.
- Configurable generation settings.
- Adjustable context length.
- Model import and management.
- CPU inference and supported GPU offloading.
- Conversation history and regeneration.

Model compatibility depends on the selected model architecture and the bundled inference engine.

### ⚡ Hardware Acceleration

OmniCore supports hardware-accelerated inference on compatible devices.

**Linux**
- NVIDIA CUDA support through compatible local llama.cpp engines.
- CPU inference fallback.
- GPU offloading information.
- Inference performance monitoring.

**Android**
- Vulkan acceleration on supported GPUs.
- CPU fallback when Vulkan is unavailable.
- GPU capability detection.
- GPU offloading diagnostics.

Actual performance depends on your hardware, drivers, model size, and configuration.

### 🤖 AI Agent — Linux

OmniCore includes an Agent mode for more advanced interactions.

- Switch between Chat and Agent modes.
- Execute supported tools when necessary.
- Perform multi-step tasks.
- Control filesystem access through permissions.
- Inspect agent activity.
- Ask ordinary questions without unnecessary tool calls.

Tool availability depends on the installed configuration.

### 💬 Conversations

- Real-time response streaming.
- Conversation history.
- Response regeneration.
- Message copying.
- Generation cancellation.
- Model selection.
- Context and inference statistics.

### 📊 Performance Statistics

Monitor your local AI inference.

Available metrics may include:

- Tokens per second.
- Input and output tokens.
- Time to first token (TTFT).
- Total generation time.
- Context usage.
- GPU offloading information.
- CPU/GPU execution details.

Android includes compact response statistics with expandable details.

### 🎨 Customizable Interface

- Modern desktop and mobile interfaces.
- Multiple desktop themes.
- Responsive layouts.
- Adjustable desktop interface scaling.
- Polish and English localization.
- Model management and settings.

---


## 🛠️ Installation

### 🐧 Linux

**Requirements**
- Linux x86_64.
- Compatible system libraries.
- Optional NVIDIA GPU and compatible CUDA environment for GPU acceleration.

**Steps**

1. Download the latest AppImage.
2. Open a terminal in the download directory.
3. Make the file executable.
4. Launch OmniCore.

```bash
chmod +x OmniCore-1.0.0-x86_64.AppImage
./OmniCore-1.0.0-x86_64.AppImage
```

The AppImage includes a CPU inference engine. CUDA acceleration requires a compatible local CUDA-enabled engine.

### 🤖 Android

**Requirements**
- Android 8.0 or newer (API 26+).
- ARM64 device.
- Sufficient storage and memory for your selected models.
- Compatible Vulkan GPU and drivers for optional Vulkan acceleration.

**Steps**

1. Download the official release APK.
2. Open the APK on your Android device.
3. Allow installation from the selected source if prompted.
4. Install and launch OmniCore.
5. Import a compatible GGUF model.

> **Upgrading from Beta builds:** The official 1.0.0 APK uses a production signing certificate. Previous debug-signed installations may require uninstalling the old version before installing Stable. Back up important data first.

---

## 🧩 Supported Technologies

| Component | Technology |
|---|---|
| Linux desktop | Python, PySide6 / Qt6 |
| Android | Kotlin, Jetpack Compose |
| AI inference | llama.cpp |
| Model format | GGUF |
| Linux GPU acceleration | NVIDIA CUDA |
| Android GPU acceleration | Vulkan |
| Backend | FastAPI |
| Database | SQLite |
| API | REST / WebSocket |

---

## 🔒 Privacy

OmniCore is designed around local AI execution.

Running a local model does not require sending your prompts to an external AI provider.

Some optional features, such as online tools, model downloads, or external integrations, may require network access.

Always review permissions before granting an AI agent access to local files.

---

## 👨‍💻 Development

OmniCore is open source and welcomes contributions.

### Clone the Repository

```bash
git clone https://github.com/vex2137/OmniCore.git
cd OmniCore
```

### Linux Development

The backend uses Python 3.12+ and `uv`.

```bash
uv sync --frozen --extra desktop
uv run --frozen omnicore-desktop
```

### Run Tests

```bash
uv sync --frozen --extra desktop --group gui-test --group packaging
uv run --frozen pytest
```

Android development requires a compatible Android SDK, JDK, Gradle environment, and native inference libraries.

See the documentation for additional build instructions.

---

## 📚 Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Linux Desktop](docs/LINUX_DESKTOP.md)
- [Android](docs/ANDROID.md)
- [AppImage](docs/APPIMAGE.md)
- [CUDA Configuration](docs/CUDA.md)
- [AI Engines](docs/ENGINES.md)
- [Roadmap](docs/ROADMAP.md)
- [Changelog](CHANGELOG.md)
- [Release Notes — 1.0.0](docs/RELEASE_NOTES_1.0.0.md)

---

## 🗺️ Roadmap

OmniCore will continue evolving beyond its first stable release.

Areas of future development include:

- Expanded model compatibility.
- Improved inference performance.
- More advanced agent capabilities.
- Additional hardware acceleration improvements.
- Expanded AI functionality.
- Further desktop and Android improvements.
- Image generation and other AI modules.

Features listed here are planned directions, not commitments or existing functionality.

---

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome.

If you discover a problem or have an idea for improvement, open an issue in the repository.

**[Report an Issue](https://github.com/vex2137/OmniCore/issues)**

Please avoid including personal information, API keys, or private model data in bug reports.

---

## 📄 License

OmniCore is released under the **MIT License**.

See [LICENSE](LICENSE) for details.

Third-party dependencies and model files may have their own licenses.

---

<div align="center">

### 🚀 OmniCore 1.0.0

**Local AI. Open Source. Built for Your Hardware.**

[⬇️ Download OmniCore](https://github.com/vex2137/OmniCore/releases/latest)

Made with ❤️ by [vex2137](https://github.com/vex2137)

</div>
