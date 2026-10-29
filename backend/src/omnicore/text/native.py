"""Bounded native-engine discovery and PyInstaller-safe native subprocess environment."""

import os
import shutil
import sys
from pathlib import Path


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
