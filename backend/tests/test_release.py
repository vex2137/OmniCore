import importlib.metadata
import json
import tomllib
from pathlib import Path

from packaging.version import Version

from omnicore import __version__
from omnicore.release import build_info, distribution_version, package_version, release_channel


def test_version_has_one_source_and_matches_installed_package():
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert "version" in project["project"]["dynamic"]
    assert "version" not in project["project"]
    canonical = json.loads((root / "backend/src/omnicore/distribution.json").read_text())["version"]
    assert distribution_version() == canonical
    assert __version__ == package_version() == str(Version(canonical))
    assert Version(importlib.metadata.version("omnicore")) == Version(__version__)
    assert release_channel() == "beta"


def test_source_provenance_is_explicit_about_missing_build_date():
    info = build_info()
    assert info["version"] == distribution_version()
    assert len(info["source_commit"]) == 40
    assert info["built_at"] is None
    assert info["channel"] == "beta"
