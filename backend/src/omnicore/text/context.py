"""Conservative context selection stored alongside each model's metadata."""

from pathlib import Path

CONTEXT_PRESETS = (2048, 4096, 8192, 16384, 32768, 65536, 131072)
AUTO_TIERS = (2048, 4096, 8192, 16384, 32768)


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


def context_settings(model, available_memory_bytes: int | None = None):
    metadata = model.get("metadata", {}) if isinstance(model, dict) else model.metadata
    size_bytes = (
        model.get("size_bytes", 0) if isinstance(model, dict) else getattr(model, "size_bytes", 0)
    )
    saved = metadata.get("desktop_context", {})
    if not isinstance(saved, dict):
        saved = {}
    limit = model_context_limit(model)
    maximum = min(1_000_000, limit) if limit else 1_000_000

    mem_bytes = (
        available_memory_bytes
        if isinstance(available_memory_bytes, int) and available_memory_bytes > 0
        else (_system_available_memory_bytes() if size_bytes >= 10 * 1024 * 1024 else None)
    )
    auto_reason = "safe_fallback"
    if limit is not None and size_bytes > 0 and mem_bytes is not None:
        weights_bytes = int(size_bytes * 1.15)
        safety_margin = max(512 * 1024**2, int(mem_bytes * 0.15))
        kv_budget = mem_bytes - weights_bytes - safety_margin
        bytes_per_token = max(64 * 1024, int(size_bytes / 16384))
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
            bytes_per_token = max(64 * 1024, int(size_bytes / 16384))
            memory_warning = (weights_bytes + effective * bytes_per_token) > (
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
        "memory_warning": memory_warning,
    }
