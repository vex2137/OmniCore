"""Bounded diagnostic export with private paths, prompts and credentials omitted."""

import json
import os
import platform as host_platform
import re
import tempfile
from pathlib import Path

from omnicore.release import build_info, distribution_version


def diagnostic_report(window, platform):
    def safe(value):
        text = str(value)[:512]
        token = getattr(window.api, "_token", "")
        if token:
            text = text.replace(token, "<redacted>")
        text = re.sub(r"(?:sk-|hf_)[A-Za-z0-9_-]{12,}", "<redacted>", text)
        text = re.sub(r"/(?:home|Users)/[^/\s]+", "~", text)
        return text

    def number(value):
        return value if type(value) is int and value >= 0 else None

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
        version = re.search(
            r"\b\d+(?:\.\d+){0,3}(?: \([a-f0-9]{7,40}\))?", str(info.get("version") or "")
        )
        entry["version"] = version.group(0) if version else None
        entry["gpu_devices"] = [safe(device) for device in record.get("gpu_devices", [])[:16]]
        entry["execution_device"] = (
            safe(record["execution_device"]) if record.get("execution_device") else None
        )
        entry["gpu_offloaded_layers"] = number(record.get("gpu_offloaded_layers"))
        entry["nvidia"] = [
            {
                "name": safe(gpu.get("name", "")),
                "driver_version": safe(gpu.get("driver_version", "")),
                "total_bytes": number(gpu.get("total_bytes")),
                "free_bytes": number(gpu.get("free_bytes")),
            }
            for gpu in record.get("nvidia_devices", [])[:8]
        ]
        entry["candidate_errors"] = [
            safe(candidate["error_code"])
            for candidate in record.get("candidates", [])
            if candidate.get("error_code")
        ][:16]
        engines.append(entry)
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    desktop = next(
        (name for name in ("KDE", "GNOME", "XFCE", "LXQT", "MATE") if name in desktop), "unknown"
    )
    hardware = getattr(window, "diagnostic_snapshot", {}).get("hardware", {})
    models = [
        {
            "name": safe(record["name"]),
            "file": "<model-dir>/" + safe(Path(record["location"]).name),
            "size_bytes": number(record.get("size_bytes")),
            "backend": record["backend"],
            "format": record.get("format"),
            "context": {
                key: (
                    getattr(window, "model_contexts", {}).get(record["id"], {}).get(key)
                    if key == "mode"
                    and getattr(window, "model_contexts", {}).get(record["id"], {}).get(key)
                    in {"auto", "manual"}
                    else number(
                        getattr(window, "model_contexts", {}).get(record["id"], {}).get(key)
                    )
                )
                for key in ("mode", "effective_tokens", "applied_tokens", "maximum")
            },
        }
        for record in window.models[:100]
    ]
    last = getattr(window, "last_job", None) or {}
    process = getattr(window.session, "process", None)
    return {
        "schema_version": 2,
        "build": build_info(),
        "system": {
            "os": host_platform.system(),
            "release": host_platform.release(),
            "architecture": host_platform.machine(),
            "desktop": desktop,
        },
        "hardware": {
            key: number(hardware.get(key))
            for key in ("cpu_count", "ram_total_bytes", "ram_available_bytes", "disk_free_bytes")
        },
        "models": models,
        "last_generation": {
            "state": last.get("state"),
            "error_code": safe(last["error_code"]) if last.get("error_code") else None,
        },
        "distribution_version": distribution_version(),
        "ui": {
            "platform": platform if platform in {"xcb", "wayland", "offscreen"} else "other",
            "locale": window.config.locale,
            "theme": window.config.theme,
        },
        "backend": {
            "connected": bool(window.is_connected),
            "owned": bool(window.session.owned),
            "owned_pid": process.processId() if process and window.session.owned else None,
        },
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
