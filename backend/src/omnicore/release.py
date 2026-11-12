"""One canonical distribution version and provenance for source/frozen clients."""

import json
import shutil
import subprocess
import sys
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from packaging.version import Version


def distribution_version() -> str:
    return json.loads(files("omnicore").joinpath("distribution.json").read_text())["version"]


def package_version() -> str:
    return str(Version(distribution_version()))


def release_channel() -> str:
    pre = Version(distribution_version()).pre
    return {"a": "alpha", "b": "beta", "rc": "rc"}.get(pre[0], "stable") if pre else "stable"


@lru_cache(maxsize=1)
def build_info() -> dict:
    resource = files("omnicore").joinpath("build_info.json")
    if resource.is_file():
        record = json.loads(resource.read_text())
        if record.get("version") != distribution_version():
            raise ValueError("Build metadata version mismatch")
        return record
    commit = None
    if not getattr(sys, "frozen", False):
        try:
            commit = subprocess.check_output(  # noqa: S603,S607 — fixed metadata command.
                [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[3],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "version": distribution_version(),
        "channel": release_channel(),
        "source_commit": commit,
        "built_at": None,
    }
