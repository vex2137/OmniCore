"""Asynchronous system and process resource monitoring (CPU, RAM, GPU, VRAM)."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal


@dataclass
class ResourceSnapshot:
    cpu_percent: float | None = None
    cpu_temp_c: float | None = None
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    gpu_name: str | None = None
    gpu_util_percent: float | None = None
    vram_used_bytes: int | None = None
    vram_total_bytes: int | None = None
    gpu_temp_c: float | None = None
    app_ram_bytes: int | None = None
    engine_ram_bytes: int | None = None
    engine_vram_bytes: int | None = None


def read_cpu_stat(path: Path = Path("/proc/stat")) -> tuple[int, int] | None:
    """Return (idle_ticks, total_ticks) from Linux /proc/stat."""
    with suppress(OSError, ValueError):
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        parts = first.split()
        if parts[0] != "cpu" or len(parts) < 5:
            return None
        nums = [int(x) for x in parts[1:]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return idle, sum(nums)
    return None


def compute_cpu_percent(
    previous: tuple[int, int] | None, current: tuple[int, int] | None
) -> float | None:
    if previous is None or current is None:
        return None
    idle_delta = current[0] - previous[0]
    total_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    usage = max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))
    return round(usage, 1)


def read_meminfo(path: Path = Path("/proc/meminfo")) -> tuple[int | None, int | None]:
    """Return (used_bytes, total_bytes) from Linux /proc/meminfo."""
    values: dict[str, int] = {}
    with suppress(OSError, ValueError):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            fields = rest.strip().split()
            if not fields:
                continue
            values[key] = int(fields[0]) * 1024
    total = values.get("MemTotal")
    if not total or total <= 0:
        return None, None
    available = values.get("MemAvailable")
    if available is None:
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    used = max(0, total - available)
    return used, total


def read_cpu_temp_c(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    thermal_root: Path = Path("/sys/class/thermal"),
) -> float | None:
    """Read Linux CPU package temperature in Celsius when exposed by hwmon or thermal_zone."""
    preferred = ("k10temp", "zenpower", "coretemp", "acpitz", "x86_pkg_temp")
    candidates: list[tuple[int, float]] = []
    if hwmon_root.is_dir():
        with suppress(OSError):
            for entry in hwmon_root.iterdir():
                name_file = entry / "name"
                if not name_file.is_file():
                    continue
                sensor_name = (
                    name_file.read_text(encoding="utf-8", errors="replace").strip().casefold()
                )
                rank = next(
                    (i for i, tag in enumerate(preferred) if tag in sensor_name),
                    99,
                )
                if rank == 99 and "cpu" not in sensor_name and "tctl" not in sensor_name:
                    continue
                for temp_file in sorted(entry.glob("temp*_input")):
                    with suppress(OSError, ValueError):
                        raw = int(temp_file.read_text(encoding="utf-8", errors="replace").strip())
                        c = raw / 1000.0 if raw > 1000 else float(raw)
                        if -20.0 <= c <= 130.0:
                            candidates.append((rank, round(c, 1)))
                            break
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    if thermal_root.is_dir():
        with suppress(OSError):
            for zone in sorted(thermal_root.glob("thermal_zone*")):
                type_file = zone / "type"
                temp_file = zone / "temp"
                if not (type_file.is_file() and temp_file.is_file()):
                    continue
                ztype = type_file.read_text(encoding="utf-8", errors="replace").strip().casefold()
                if any(tag in ztype for tag in ("x86_pkg_temp", "acpitz", "k10temp", "cpu")):
                    with suppress(OSError, ValueError):
                        raw = int(temp_file.read_text(encoding="utf-8", errors="replace").strip())
                        c = raw / 1000.0 if raw > 1000 else float(raw)
                        if -20.0 <= c <= 130.0:
                            return round(c, 1)
    return None


def read_process_rss_bytes(pid: int) -> int | None:
    if not pid or pid <= 0:
        return None
    status_path = Path(f"/proc/{pid}/status")
    with suppress(OSError, ValueError):
        for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return None


def find_related_pids(
    root_pids: list[int], proc_root: Path = Path("/proc")
) -> tuple[set[int], set[int]]:
    """Return (app_pids, engine_pids) anchored strictly under known root PIDs."""
    roots = {p for p in root_pids if isinstance(p, int) and p > 0}
    if not roots:
        return set(), set()
    parent_to_children: dict[int, list[tuple[int, str]]] = {}
    with suppress(OSError):
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            with suppress(OSError, ValueError):
                stat_text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
                rparen = stat_text.rfind(")")
                if rparen <= 0:
                    continue
                comm = stat_text[stat_text.find("(") + 1 : rparen].casefold()
                rest = stat_text[rparen + 2 :].split()
                if len(rest) >= 2:
                    ppid = int(rest[1])
                    parent_to_children.setdefault(ppid, []).append((pid, comm))
    app_pids: set[int] = set(roots)
    engine_pids: set[int] = set()
    queue = list(roots)
    visited = set(roots)
    while queue:
        cur = queue.pop()
        for child_pid, comm in parent_to_children.get(cur, ()):
            if child_pid in visited:
                continue
            visited.add(child_pid)
            if "llama" in comm:
                engine_pids.add(child_pid)
            else:
                app_pids.add(child_pid)
            queue.append(child_pid)
    return app_pids, engine_pids


def query_nvidia_resources(engine_pids: set[int]) -> dict:
    """Query GPU utilization, VRAM, temperature, and per-PID compute VRAM via nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    result: dict = {}
    try:
        proc = subprocess.run(  # noqa: S603
            [
                exe,
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            rows = list(csv.reader(proc.stdout.splitlines(), skipinitialspace=True))
            if rows and len(rows[0]) >= 5:
                row = rows[0]
                result["gpu_name"] = row[0].strip()[:120] or None
                with suppress(ValueError):
                    result["gpu_util_percent"] = float(row[1])
                with suppress(ValueError):
                    result["vram_used_bytes"] = int(float(row[2])) * 1024**2
                with suppress(ValueError):
                    result["vram_total_bytes"] = int(float(row[3])) * 1024**2
                with suppress(ValueError):
                    result["gpu_temp_c"] = float(row[4])
    except (OSError, subprocess.SubprocessError):
        return {}
    if engine_pids:
        try:
            apps = subprocess.run(  # noqa: S603
                [exe, "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if apps.returncode == 0 and apps.stdout.strip():
                total_vram = 0
                matched = False
                for row in csv.reader(apps.stdout.splitlines(), skipinitialspace=True):
                    if len(row) != 2:
                        continue
                    with suppress(ValueError):
                        pid_val = int(row[0])
                        if pid_val in engine_pids:
                            total_vram += int(float(row[1])) * 1024**2
                            matched = True
                if matched:
                    result["engine_vram_bytes"] = total_vram
        except (OSError, subprocess.SubprocessError):
            pass
    return result


def collect_snapshot(
    prev_cpu: tuple[int, int] | None, root_pids: list[int]
) -> tuple[ResourceSnapshot, tuple[int, int] | None]:
    curr_cpu = read_cpu_stat()
    cpu_pct = compute_cpu_percent(prev_cpu, curr_cpu)
    cpu_temp = read_cpu_temp_c()
    ram_used, ram_total = read_meminfo()
    app_pids, engine_pids = find_related_pids(root_pids)
    app_ram_vals = [read_process_rss_bytes(pid) for pid in app_pids]
    app_ram = (
        sum(v for v in app_ram_vals if v is not None)
        if any(v is not None for v in app_ram_vals)
        else None
    )
    eng_ram_vals = [read_process_rss_bytes(pid) for pid in engine_pids]
    eng_ram = (
        sum(v for v in eng_ram_vals if v is not None)
        if any(v is not None for v in eng_ram_vals)
        else None
    )
    gpu = query_nvidia_resources(engine_pids)
    snapshot = ResourceSnapshot(
        cpu_percent=cpu_pct,
        cpu_temp_c=cpu_temp,
        ram_used_bytes=ram_used,
        ram_total_bytes=ram_total,
        gpu_name=gpu.get("gpu_name"),
        gpu_util_percent=gpu.get("gpu_util_percent"),
        vram_used_bytes=gpu.get("vram_used_bytes"),
        vram_total_bytes=gpu.get("vram_total_bytes"),
        gpu_temp_c=gpu.get("gpu_temp_c"),
        app_ram_bytes=app_ram,
        engine_ram_bytes=eng_ram,
        engine_vram_bytes=gpu.get("engine_vram_bytes"),
    )
    return snapshot, curr_cpu


def _fmt_gb(value: int | None, sep: str, dash: str = "—") -> str:
    if value is None:
        return dash
    return f"{value / (1024**3):.1f}".replace(".", sep)


def _fmt_mb_or_gb(value: int | None, sep: str, dash: str = "—") -> str:
    if value is None:
        return dash
    gb = value / (1024**3)
    if gb >= 1.0:
        return f"{gb:.2f} GB".replace(".", sep)
    mb = value / (1024**2)
    return f"{mb:.0f} MB".replace(".", sep)


def format_summary(snapshot: ResourceSnapshot, tr) -> str:
    sep = tr("decimal_separator")
    dash = "—"
    cpu_pct = f"{snapshot.cpu_percent:.0f}%" if snapshot.cpu_percent is not None else dash
    cpu_temp = f" ({snapshot.cpu_temp_c:.0f}°C)" if snapshot.cpu_temp_c is not None else ""
    ram_txt = (
        f"{_fmt_gb(snapshot.ram_used_bytes, sep, dash)}/"
        f"{_fmt_gb(snapshot.ram_total_bytes, sep, dash)} GB"
        if snapshot.ram_total_bytes is not None
        else dash
    )
    gpu_pct = f"{snapshot.gpu_util_percent:.0f}%" if snapshot.gpu_util_percent is not None else dash
    gpu_temp = f" ({snapshot.gpu_temp_c:.0f}°C)" if snapshot.gpu_temp_c is not None else ""
    vram_txt = (
        f"{_fmt_gb(snapshot.vram_used_bytes, sep, dash)}/"
        f"{_fmt_gb(snapshot.vram_total_bytes, sep, dash)} GB"
        if snapshot.vram_total_bytes is not None
        else dash
    )
    return (
        f"CPU: {cpu_pct}{cpu_temp} · RAM: {ram_txt} · GPU: {gpu_pct}{gpu_temp} · VRAM: {vram_txt}"
    )


def format_details(snapshot: ResourceSnapshot, tr) -> str:
    sep = tr("decimal_separator")
    dash = "—"
    is_pl = tr("you") == "Ty"
    cpu_pct = (
        f"{snapshot.cpu_percent:.1f}%".replace(".", sep)
        if snapshot.cpu_percent is not None
        else dash
    )
    cpu_temp = (
        f"{snapshot.cpu_temp_c:.1f}°C".replace(".", sep)
        if snapshot.cpu_temp_c is not None
        else dash
    )
    ram_sys = (
        f"{_fmt_gb(snapshot.ram_used_bytes, sep, dash)} / "
        f"{_fmt_gb(snapshot.ram_total_bytes, sep, dash)} GB"
        if snapshot.ram_total_bytes is not None
        else dash
    )
    gpu_name = snapshot.gpu_name or dash
    gpu_pct = f"{snapshot.gpu_util_percent:.0f}%" if snapshot.gpu_util_percent is not None else dash
    gpu_temp = f"{snapshot.gpu_temp_c:.0f}°C" if snapshot.gpu_temp_c is not None else dash
    vram_sys = (
        f"{_fmt_gb(snapshot.vram_used_bytes, sep, dash)} / "
        f"{_fmt_gb(snapshot.vram_total_bytes, sep, dash)} GB"
        if snapshot.vram_total_bytes is not None
        else dash
    )
    app_ram = _fmt_mb_or_gb(snapshot.app_ram_bytes, sep, dash)
    eng_ram = _fmt_mb_or_gb(snapshot.engine_ram_bytes, sep, dash)
    eng_vram = _fmt_mb_or_gb(snapshot.engine_vram_bytes, sep, dash)
    if is_pl:
        return "\n".join(
            [
                f"System · CPU: {cpu_pct} · Temp. CPU: {cpu_temp} · RAM (system): {ram_sys}",
                (
                    f"GPU: {gpu_name} · Obciążenie: {gpu_pct} · "
                    f"Temp. GPU: {gpu_temp} · VRAM (system): {vram_sys}"
                ),
                (
                    f"OmniCore · Aplikacja + API (RAM): {app_ram} · "
                    f"Silnik llama-server (RAM): {eng_ram} · Silnik (VRAM): {eng_vram}"
                ),
            ]
        )
    return "\n".join(
        [
            f"System · CPU: {cpu_pct} · CPU temp: {cpu_temp} · System RAM: {ram_sys}",
            f"GPU: {gpu_name} · Load: {gpu_pct} · GPU temp: {gpu_temp} · System VRAM: {vram_sys}",
            (
                f"OmniCore · App + API RAM: {app_ram} · "
                f"llama-server RAM: {eng_ram} · Engine VRAM: {eng_vram}"
            ),
        ]
    )


class ResourceMonitor(QObject):
    """Non-blocking background sampler using one daemon thread with clean shutdown."""

    updated = Signal(object)

    def __init__(self, pid_provider, *, interval_seconds: float = 2.0, collector=None):
        super().__init__()
        self._pid_provider = pid_provider
        self._interval = max(0.5, float(interval_seconds))
        self._collector = collector or collect_snapshot
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._prev_cpu: tuple[int, int] | None = None
        self.latest: ResourceSnapshot = ResourceSnapshot()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="omnicore-resources", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                pids = list(self._pid_provider() or [])
            except Exception:
                pids = [os.getpid()]
            with suppress(Exception):
                snapshot, self._prev_cpu = self._collector(self._prev_cpu, pids)
                self.latest = snapshot
                if not self._stop_event.is_set():
                    self.updated.emit(snapshot)
            if self._stop_event.wait(self._interval):
                break

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
