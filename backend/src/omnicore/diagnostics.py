"""Read-only, bounded host diagnostics without tokens, prompts or filesystem listings."""

import os
import platform
import shutil
from pathlib import Path

from omnicore.schemas import WireModel


class HardwareSnapshot(WireModel):
    cpu_architecture: str
    cpu_count: int | None
    ram_total_bytes: int | None
    ram_available_bytes: int | None
    disk_free_bytes: int


def hardware_snapshot(directory: Path) -> HardwareSnapshot:
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                memory[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return HardwareSnapshot(
        cpu_architecture=platform.machine(),
        cpu_count=os.cpu_count(),
        ram_total_bytes=memory.get("MemTotal"),
        ram_available_bytes=memory.get("MemAvailable"),
        disk_free_bytes=shutil.disk_usage(directory).free,
    )
