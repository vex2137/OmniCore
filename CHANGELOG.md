# Changelog

## 1.0.0

### Android
- Compact assistant message statistics footer (`speed · elapsed · Details`) with accessible expandable full metrics panel supporting EN/PL and light/dark themes.
- Preserved partial assistant output and cancellation metrics cleanly without losing message state on stop.
- Upgraded pinned on-device `llama.cpp` runtime (`c3df4b7e`) with `lfm3` architecture support, Vulkan/Mali-G720 offload diagnostics, structural GGUF v2/v3 validation (`GgufReader`), unified-memory-safe reporting, and clean `OmniCore` release metadata.
- Added optional release keystore signing configuration (`OMNICORE_KEYSTORE_*` environment variables) in Gradle while keeping debug and unsigned APKs clearly distinguished.

### Linux Desktop & Backend
- Fixed Agent mode unnecessarily invoking `list_files` on greetings and general questions (updated conversational-first system prompt and omitted filesystem tools when no folders are granted and no filesystem intent is detected, validated on `LFM3 1.7B` and `Qwen3.5 4B`).
- Fixed premature word-wrapping of short user message bubbles (`SafeMarkdown` now re-measures with polished fonts and viewport-aware ~72% caps across window resizes and drawer toggles).
- Fixed black rectangular background bleed on Settings checkboxes (`Włącz opcjonalną integrację z Ollamą`, `Myślenie (tylko zgodne szablony modeli)`) across all 7 themes and 80–200% UI scales, with custom HiDPI checkmark icons and explicit disabled/focus/hover states.
- Expanded UI scaling support from 80% to 200% with wrapping toolbar/inspector FlowLayout controls and safe topbar compaction.
- Restricted engine VRAM budget estimation (`_available_vram_bytes`) strictly to CUDA devices.
- Updated `1.0.0` version provenance, OpenAPI contracts, and Android `versionCode` (`10` -> `11`).

## 0.1.0-rc.1

- Automatyczne wykrywanie lokalnych silników CUDA, niezależnie od silnika CPU w AppImage.
- Izolacja bibliotek AppImage, potwierdzenie offloadu, Auto fallback, VRAM i diagnostyka.
- Przyrostowa obsługa znaczników myślenia i wieloliniowego SSE; brak pustego sukcesu.
- Nazwa modelu i statystyki przy odpowiedzi, prosty wybór wykonania i zaawansowane opcje.
- Partie starszych dymków w długich rozmowach, bez utraty historii.
- Android: poprawki Alpha.3, wybór wykonania na backendzie i raportowane warstwy GPU.
- Izolowany test sprzętowy wewnątrz AppImage i instrukcja bramki Stable.

Rzeczywiste testy RTX4060, LFM3/Qwen użytkownika i telefonu pozostają do potwierdzenia.
RC APK ma testowy podpis oraz osobny identyfikator; nie zastępuje zainstalowanej Alpha.

## 0.1.0 Alpha.3

Synchronizacja kolejki i rozmów, anulowanie, snapshot modelu/statystyki, natywne
Markdown/dymki/wyszukiwanie Linux oraz systemowy język/reconnect/UX Android.
Szczegóły testów i checkpointów: docs/PROGRESS.md. Alpha.3 pozostała szkicem.

## 0.1.0 Alpha.2 / Alpha.1

Pierwsze publiczne testowe paczki Linux/Android i lokalna inferencja GGUF CPU.
