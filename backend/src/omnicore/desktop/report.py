"""A closed diagnostic schema: no prompt, path, host, identifier, token or raw logs."""

import json
import os
import tempfile
from pathlib import Path

from omnicore.release import distribution_version


def diagnostic_report(window, platform):
    engines = []
    for record in window.engines:
        info = record.get("info", {})
        if info.get("id") not in {"llama.cpp", "ollama"}:
            continue
        resources = info.get("resources") or {}
        entry = {"id": info["id"], "available": info.get("available") is True}
        for key in ("ram_bytes", "vram_bytes"):
            value = resources.get(key)
            entry[key] = value if type(value) is int and value >= 0 else None
        engines.append(entry)
    return {
        "schema_version": 1,
        "distribution_version": distribution_version(),
        "ui": {
            "platform": platform if platform in {"xcb", "wayland", "offscreen"} else "other",
            "locale": window.config.locale,
            "theme": window.config.theme,
        },
        "backend": {"connected": bool(window.is_connected), "owned": bool(window.session.owned)},
        "counts": {"models": len(window.models), "conversations": len(window.conversations)},
        "engines": engines,
    }


def save_report(path: Path, report):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as f:
            temporary = Path(f.name)
            os.chmod(temporary, 0o600)
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
