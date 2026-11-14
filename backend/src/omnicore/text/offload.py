"""Automatic GGUF layer offload estimation and CUDA OOM retry helpers."""

from __future__ import annotations

import math
import re
from contextlib import suppress
from pathlib import Path

from omnicore.text.gguf import read_gguf

OFFLOAD_MODES = ("auto", "max", "manual", "cpu")
MAX_OOM_RETRIES = 3

_OOM_PATTERNS = (
    "out of memory",
    "insufficient memory",
    "cudamalloc failed",
    "cudaerrormemoryallocation",
    "failed to allocate cuda",
    "ggml_backend_cuda_buffer_type_alloc_buffer",
)


def resolve_offload_mode(parameters) -> str:
    """Resolve explicit or legacy offload mode from generation parameters."""
    explicit = getattr(parameters, "gpu_offload_mode", None)
    if explicit in OFFLOAD_MODES:
        return explicit
    device = getattr(parameters, "device", "cpu")
    layers = getattr(parameters, "gpu_layers", 0)
    if device == "cpu":
        return "cpu"
    if device == "auto":
        return "auto"
    if layers >= 999:
        return "max"
    return "manual"


def _meta_int(inner: dict, architecture: str | None, suffix: str) -> int | None:
    if architecture:
        val = inner.get(f"{architecture}.{suffix}")
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    for key, val in inner.items():
        if (
            isinstance(key, str)
            and key.endswith(f".{suffix}")
            and isinstance(val, int)
            and not isinstance(val, bool)
            and val > 0
        ):
            return val
    return None


def inspect_gguf_layout(path: Path) -> dict | None:
    """Read GGUF header layout hints safely without loading tensor weights."""
    try:
        if not path.is_file():
            return None
        size_bytes = path.stat().st_size
        if size_bytes < 64:
            return None
        with path.open("rb") as stream:
            info = read_gguf(stream)
    except Exception:
        return None
    meta = info.get("metadata", {}) if isinstance(info, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    arch = info.get("architecture") if isinstance(info, dict) else None
    emb = _meta_int(meta, arch, "embedding_length")
    return {
        "file_size_bytes": size_bytes,
        "architecture": arch,
        "block_count": _meta_int(meta, arch, "block_count"),
        "head_count_kv": _meta_int(meta, arch, "attention.head_count_kv")
        or _meta_int(meta, arch, "attention.head_count"),
        "key_length": _meta_int(meta, arch, "attention.key_length") or 128,
        "value_length": _meta_int(meta, arch, "attention.value_length")
        or _meta_int(meta, arch, "attention.key_length")
        or 128,
        "embedding_length": emb,
    }


def estimate_kv_cache_bytes(layout: dict, context_size: int) -> int:
    """Estimate FP16 KV cache VRAM footprint for the configured context size."""
    block_count = layout.get("block_count") or 32
    head_kv = layout.get("head_count_kv")
    if head_kv:
        key_len = layout.get("key_length") or 128
        val_len = layout.get("value_length") or key_len
        bytes_per_token_per_layer = head_kv * (key_len + val_len) * 2
        return max(1, context_size * block_count * bytes_per_token_per_layer)
    size_bytes = layout.get("file_size_bytes") or 0
    bytes_per_token = max(64 * 1024, int(size_bytes / 16384))
    return max(1, context_size * bytes_per_token)


def estimate_auto_gpu_layers(
    path: Path,
    context_size: int,
    fallback_layers: int,
    free_vram_bytes: int | None,
    layout: dict | None = None,
) -> tuple[int, int | None, str]:
    """Estimate safe GPU layer count from VRAM budget, weights, KV cache, and overhead."""
    info = layout if layout is not None else inspect_gguf_layout(path)
    if not info or not info.get("file_size_bytes"):
        return max(1, fallback_layers or 99), None, "fallback_default"
    total_layers = info.get("block_count")
    if free_vram_bytes is None or free_vram_bytes <= 0:
        if total_layers:
            chosen = min(fallback_layers, total_layers) if fallback_layers else total_layers
            return max(1, chosen), total_layers, "vram_unknown"
        return max(1, fallback_layers or 99), None, "vram_unknown"

    overhead = max(512 * 1024**2, int(free_vram_bytes * 0.10))
    compute_buffer = 256 * 1024**2
    vram_budget = max(0, free_vram_bytes - overhead - compute_buffer)
    kv_total = estimate_kv_cache_bytes(info, context_size)
    weights_bytes = info["file_size_bytes"]

    if not total_layers:
        full_cost = int(weights_bytes * 1.05) + kv_total
        if full_cost <= vram_budget:
            return max(1, fallback_layers or 99), None, "fits_in_vram"
        ratio = max(0.05, min(0.95, vram_budget / max(1, full_cost)))
        est = max(1, int((fallback_layers or 32) * ratio))
        return est, None, "vram_partial_offload"

    full_cost = int(weights_bytes * 1.03) + kv_total
    if full_cost <= vram_budget:
        return total_layers, total_layers, "fits_in_vram"

    per_layer_weights = weights_bytes / (total_layers + 2)
    per_layer_kv = kv_total / max(1, total_layers)
    per_layer_cost = max(1.0, per_layer_weights + per_layer_kv)
    fit = math.floor(vram_budget / per_layer_cost)
    chosen = max(1, min(total_layers - 1, fit))
    return chosen, total_layers, "vram_partial_offload"


def parse_startup_layers(log_text: str) -> tuple[int | None, int | None]:
    """Parse (offloaded_layers, total_layers) from llama-server startup logs."""
    if not log_text:
        return None, None
    offload = re.search(r"offloaded\s+(\d+)/(\d+)\s+layers", log_text)
    if offload:
        return int(offload[1]), int(offload[2])
    n_layer = re.search(r"n_layer\s*=\s*(\d+)", log_text)
    if n_layer:
        with suppress(ValueError):
            return None, int(n_layer[1])
    repeating = re.search(r"offloading\s+(\d+)\s+repeating layers", log_text)
    if repeating:
        return int(repeating[1]), None
    return None, None


def is_cuda_oom_log(log: bytes | str) -> bool:
    """Detect CUDA/VRAM out-of-memory failures from engine stderr logs."""
    if isinstance(log, (bytes, bytearray)):
        text = log.decode("utf-8", errors="replace")
    else:
        text = str(log)
    lowered = text.casefold()
    return any(pattern in lowered for pattern in _OOM_PATTERNS)


def next_stepdown_layers(current_layers: int, detected_total: int | None) -> int | None:
    """Compute strictly smaller positive GPU layer count for bounded OOM retry."""
    if current_layers <= 1:
        return None
    if detected_total and 0 < detected_total < current_layers:
        return max(1, int(detected_total * 0.75))
    step = max(1, (current_layers + 3) // 4)
    nxt = current_layers - step
    return max(1, nxt) if nxt < current_layers else current_layers - 1
