"""Conservative context selection stored alongside each model's metadata."""

import shutil
import subprocess
import time
from pathlib import Path

from omnicore.text.offload import (
    estimate_kv_bytes_per_token,
    estimate_ssm_state_bytes,
    layout_from_metadata,
)

CONTEXT_PRESETS = (2048, 4096, 8192, 16384, 32768, 65536, 131072)
AUTO_TIERS = (2048, 4096, 8192, 16384, 32768)
_VRAM_CACHE: tuple[float | None, int | None] = (None, None)


def model_context_limit(model):
    metadata = model.get("metadata", {}) if isinstance(model, dict) else model.metadata
    inner = metadata.get("metadata", {})
    if not isinstance(inner, dict):
        return None
    architecture = metadata.get("architecture") or inner.get("general.architecture")
    value = inner.get(f"{architecture}.context_length") if architecture else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 128:
        return value
    for key, candidate in inner.items():
        if (
            isinstance(key, str)
            and key.endswith(".context_length")
            and isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and candidate >= 128
        ):
            return candidate
    return None


def _system_available_memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key == "MemAvailable":
                return int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return None


def _system_vram_total_bytes() -> int | None:
    """Return total primary GPU VRAM in bytes with a short cache, or None when absent."""
    global _VRAM_CACHE
    now = time.monotonic()
    cached_at, cached_val = _VRAM_CACHE
    if cached_at is not None and (now - cached_at) < 10.0:
        return cached_val
    executable = shutil.which("nvidia-smi")
    if not executable:
        _VRAM_CACHE = (now, None)
        return None
    from omnicore.text.native import native_environment

    total = None
    try:
        proc = subprocess.run(  # noqa: S603
            [executable, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=1.5,
            env=native_environment(),
            check=False,
        )
        if proc.returncode == 0:
            values = []
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    values.append(int(line) * 1024**2)
            if values:
                total = max(values)
    except (OSError, subprocess.SubprocessError, ValueError):
        total = None
    _VRAM_CACHE = (now, total)
    return total


def _layout_from_metadata(model, size_bytes: int) -> dict:
    metadata = model.get("metadata", {}) if isinstance(model, dict) else model.metadata
    inner = metadata.get("metadata", {})
    if not isinstance(inner, dict):
        inner = {}
    arch = metadata.get("architecture") or inner.get("general.architecture")
    return layout_from_metadata(inner, arch, size_bytes)


def context_settings(
    model,
    available_memory_bytes: int | None = None,
    *,
    device: str | None = None,
    gpu_offload_mode: str | None = None,
):
    metadata = model.get("metadata", {}) if isinstance(model, dict) else model.metadata
    size_bytes = (
        model.get("size_bytes", 0) if isinstance(model, dict) else getattr(model, "size_bytes", 0)
    )
    backend = model.get("backend") if isinstance(model, dict) else getattr(model, "backend", None)
    params = (
        model.get("parameters") if isinstance(model, dict) else getattr(model, "parameters", None)
    ) or {}
    eff_device = device if device is not None else params.get("device", "auto")
    eff_mode = gpu_offload_mode if gpu_offload_mode is not None else params.get("gpu_offload_mode")
    cpu_only = backend == "ollama" or eff_mode == "cpu" or eff_device == "cpu"

    saved = metadata.get("desktop_context", {})
    if not isinstance(saved, dict):
        saved = {}
    limit = model_context_limit(model)
    maximum = min(1_000_000, limit) if limit else 1_000_000

    memory_kind: str | None = None
    mem_bytes: int | None = None
    if isinstance(available_memory_bytes, int) and available_memory_bytes > 0:
        mem_bytes = available_memory_bytes
        memory_kind = "ram" if cpu_only else "vram"
    elif size_bytes >= 10 * 1024 * 1024:
        if not cpu_only:
            vram = _system_vram_total_bytes()
            if vram and vram > 0:
                mem_bytes = vram
                memory_kind = "vram"
            elif eff_device == "auto" and eff_mode in (None, "auto"):
                mem_bytes = _system_available_memory_bytes()
                if mem_bytes:
                    memory_kind = "ram"
        else:
            mem_bytes = _system_available_memory_bytes()
            if mem_bytes:
                memory_kind = "ram"

    layout = _layout_from_metadata(model, size_bytes)
    bytes_per_token = estimate_kv_bytes_per_token(layout)
    ssm_bytes = estimate_ssm_state_bytes(layout)
    auto_reason = "safe_fallback"
    if limit is not None and size_bytes > 0 and mem_bytes is not None:
        weights_bytes = int(size_bytes * 1.15)
        safety_margin = max(512 * 1024**2, int(mem_bytes * 0.15))
        kv_budget = mem_bytes - weights_bytes - safety_margin - ssm_bytes
        chosen = min(2048, maximum)
        for tier in AUTO_TIERS:
            if tier <= maximum and tier * bytes_per_token <= kv_budget:
                chosen = tier
        automatic = chosen
        auto_reason = "memory_estimated"
    else:
        automatic = min(2048, maximum)

    manual = saved.get("manual_tokens")
    if not isinstance(manual, int) or isinstance(manual, bool) or not 128 <= manual <= maximum:
        manual = automatic
    mode = saved.get("mode") if saved.get("mode") in {"auto", "manual"} else "auto"
    effective = manual if mode == "manual" else automatic

    memory_warning = False
    if mode == "manual":
        if mem_bytes is not None and size_bytes > 0:
            weights_bytes = int(size_bytes * 1.15)
            safety_margin = max(512 * 1024**2, int(mem_bytes * 0.15))
            memory_warning = (weights_bytes + ssm_bytes + effective * bytes_per_token) > (
                mem_bytes - safety_margin
            ) or effective >= 65536
        elif effective >= 32768:
            memory_warning = True

    return {
        "mode": mode,
        "manual_tokens": manual,
        "automatic_tokens": automatic,
        "effective_tokens": effective,
        "maximum": maximum,
        "declared_limit": limit,
        "auto_reason": auto_reason,
        "memory_kind": memory_kind,
        "memory_warning": memory_warning,
    }
