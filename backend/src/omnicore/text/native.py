"""Bounded native-engine discovery and PyInstaller-safe native subprocess environment."""

import os
import shutil
import sys
from pathlib import Path


def restricted_cpu_threads():
    """Bound native pools only when affinity or visible cgroup v2 quota restricts CPUs.

    Polling pools can consume an entire container quota while waiting for each
    other. On unrestricted hosts keep llama.cpp's native CPU/thread selection.
    """
    logical = os.cpu_count() or 1
    try:
        available = min(logical, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        available = logical
    quota_restricted = False
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max" and int(quota) > 0 and int(period) > 0:
            quota_restricted = int(quota) < logical * int(period)
            available = min(available, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    if available >= logical and not quota_restricted:
        return None

    def setting(name, default):
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError:
            value = default
        return min(available, value) if value > 0 else default

    threads = setting("LLAMA_ARG_THREADS", available)
    return threads, setting("LLAMA_ARG_THREADS_BATCH", threads)


def engine_candidates(configured_cuda=None, configured_cpu=None):
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")))
    candidates = [
        configured_cuda,
        data / "omnicore/engines/cuda/llama-server",
        data / "omnicore/engines/cuda/bin/llama-server",
        home / "llama.cpp/build-cuda/bin/llama-server",
        home / "llama.cpp/build/bin/llama-server",
        home / ".local/bin/llama-server",
        shutil.which("llama-server"),
        Path("/usr/local/bin/llama-server"),
        Path("/usr/bin/llama-server"),
        configured_cpu,
    ]
    result = []
    for candidate in candidates:
        if candidate:
            path = Path(candidate).absolute()
            if path not in result:
                result.append(path)
    return result


def native_environment(environment=None, *, frozen=None):
    result = dict(os.environ if environment is None else environment)
    if frozen if frozen is not None else getattr(sys, "frozen", False):
        # The guard runs AFTER the bootloader: external CUDA must not load AppImage's
        # libstdc++/OpenSSL. Preserve the user's original CUDA runtime search path.
        original = result.get("LD_LIBRARY_PATH_ORIG", "")
        internal = getattr(sys, "_MEIPASS", None)
        entries = [value for value in original.split(os.pathsep) if value]
        if internal:
            root = Path(internal).resolve()
            entries = [value for value in entries if not Path(value).resolve().is_relative_to(root)]
        restored = os.pathsep.join(dict.fromkeys(entries))
        if restored:
            result["LD_LIBRARY_PATH"] = restored
            result["LD_LIBRARY_PATH_ORIG"] = restored
        else:
            result.pop("LD_LIBRARY_PATH", None)
            result.pop("LD_LIBRARY_PATH_ORIG", None)
    return result
