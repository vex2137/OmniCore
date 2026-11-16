# RC8: history and chat verification

Actual PySide6 windows rendered with Qt's offscreen platform, not generated artwork.
`chat-*.png` use a manually seeded API history to inspect layout at 1280×720,
1366×768, 1920×1080 and 2560×1440 and in compact mode. Those sample messages
are not an inference result. `gguf-cpu.png` and `regenerated-cpu.png` show real
SmolLM2-135M-Instruct-Q4_K_M responses using the existing llama.cpp CPU engine;
JSON reports contain the measured generation data. No weights are included.
These checks do not verify a physical GPU, Wayland or X11.

Regenerate creates a new conversation branch from the history before the latest
user message and submits that message again. The original conversation remains
unchanged. The context bar describes the last backend request, not an estimate
of the entire history. TTFT retains the backend job-start definition, including
preparation and first reasoning/content token; it does not measure UI latency.

Pinning is stored in each conversation's existing JSON record in SQLite, so old
records default to unpinned without a schema rebuild. Renaming does not clear pins.
