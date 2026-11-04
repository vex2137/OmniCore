"""Conservative context selection stored alongside each model's metadata."""


def model_context_limit(model):
    metadata = model.get("metadata", {}) if isinstance(model, dict) else model.metadata
    inner = metadata.get("metadata", {})
    if not isinstance(inner, dict):
        return None
    architecture = metadata.get("architecture") or inner.get("general.architecture")
    value = inner.get(f"{architecture}.context_length") if architecture else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 128:
        return value
    return None


def context_settings(model):
    metadata = model.get("metadata", {}) if isinstance(model, dict) else model.metadata
    saved = metadata.get("desktop_context", {})
    if not isinstance(saved, dict):
        saved = {}
    limit = model_context_limit(model)
    maximum = min(1_000_000, limit) if limit else 1_000_000
    manual = saved.get("manual_tokens")
    if not isinstance(manual, int) or isinstance(manual, bool) or not 128 <= manual <= maximum:
        manual = min(2048, maximum)
    mode = saved.get("mode") if saved.get("mode") in {"auto", "manual"} else "auto"
    automatic = min(2048, maximum)
    return {
        "mode": mode,
        "manual_tokens": manual,
        "effective_tokens": manual if mode == "manual" else automatic,
        "maximum": maximum,
    }
