# Optional native components: Python + Rust

This directory is the architectural boundary for future native components, not an
empty Cargo workspace. No Rust compiler, wheel or worker is required to build
OmniCore or its AppImage today. Existing Python behavior remains the reference.

## Measured decision, 2026-10-28

`benchmarks/benchmark_native_candidates.py` measures actual GGUF metadata parsing,
reference import into SQLite, full-file SHA-256, a bounded asyncio queue and a
Python process startup proxy. Raw samples and host details are versioned in
`benchmarks/linux-cpu-baseline.json`. Reproduce with an existing GGUF, outside Git:

```sh
uv run --frozen python benchmarks/benchmark_native_candidates.py \
  --gguf /absolute/model.gguf --output /tmp/omnicore-baseline.json
```

Warm-cache medians for a 105454432-byte model: parse 199.6 ms; reference import
299.1 ms; SHA-256 114.8 ms; 10000 queue handoffs 14.5 ms; interpreter startup proxy
26.8 ms. A 4 GiB sparse fixture with the same metadata parsed in 211.1 ms; full
SHA-256 took 4649.0 ms. The padded file is not valid inference weights. Nine
sequential samples per operation, three for the full 4 GiB checksum. These are not cold-disk, multi-GB,
GPU, cancellation, process cleanup or end-to-end application benchmarks.
The import reads bounded metadata and references weights without copying them.
SHA-256 already uses native OpenSSL through hashlib. Queue overhead is below model
execution latency. Qt uses asynchronous networking; importing does not block its
main thread. No sustained, measured application bottleneck justifies an FFI or IPC
implementation yet. Parsing latency alone does not establish that Rust would
improve end-to-end use enough to outweigh its maintenance/build cost.

## Admission contract for the first Rust component

1. Capture a representative large-file/resource/process/concurrency workload and
   profile Python, including I/O and native-library time. Establish a user-visible
   budget before writing a prototype, e.g. p95 below 100 ms or a 20% RSS reduction.
2. Prefer bounded metadata/file transforms with PyO3 + maturin when short, safe
   native calls can release the GIL. Preserve the Python signature, error codes,
   bounded memory, descriptor/O_NOFOLLOW policy and Python fallback. Do not turn
   this into an alternate inference implementation.
3. Use a separate Rust process for long-running operations only when isolation
   is useful. Version messages, bound frames and concurrency, use authenticated
   local IPC, cancel cooperatively, supervise death and do not transfer ownership
   of SQLite migrations or scheduling policies to the worker.
4. Prove equal results, malformed-input and crash handling, cancellation, fallback
   on missing/incompatible binaries, and a measured benefit including FFI/IPC.
5. The first justified component gets its own named crate and lockfile here,
   explicit minimum Rust/toolchain pin, license/source record and opt-in build.
   CI must exercise Python-only and Rust modes. AppImage must bundle the tested
   Linux x86_64 wheel/worker and still launch when the optional component fails.

Linux wheels add glibc/ABI and toolchain support costs. PyO3 calls share the Python
process and cannot isolate native crashes. Workers add serialization and lifecycle
costs. Android Alpha remains an API client; JNI/UniFFI requires a separate decision.
Web remains an API client; WebAssembly is not a prerequisite. llama.cpp/Ollama and
future image engines retain inference/GPU responsibilities.
