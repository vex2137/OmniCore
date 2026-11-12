"""Small tests for the workflow-side package guard, without building an image."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/test_agents_appimage.py"
spec = importlib.util.spec_from_file_location("agent_package_check", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.mark.parametrize("fault", [None, "sha", "model_declaration", "gguf", "engine", "pyside"])
def test_package_source_content_and_integrity_guard(tmp_path, fault):
    engine = tmp_path / "usr/bin/engines/llama-server"
    engine.parent.mkdir(parents=True)
    engine.write_bytes(b"synthetic executable")
    pyside = tmp_path / "usr/bin/_internal/PySide6"
    if fault != "pyside":
        pyside.mkdir(parents=True)
    manifest = {
        "source_commit": "a" * 40,
        "model_weights": fault == "model_declaration",
        "engine": {"packaged_sha256": hashlib.sha256(engine.read_bytes()).hexdigest()},
    }
    (tmp_path / "build-manifest.json").write_text(json.dumps(manifest))
    if fault == "gguf":
        (tmp_path / "weights.gguf").write_bytes(b"GGUF")
    if fault == "engine":
        engine.write_bytes(b"changed")
    if fault:
        with pytest.raises(RuntimeError):
            check.verify_tree(tmp_path, "b" * 40 if fault == "sha" else "a" * 40)
    else:
        assert check.verify_tree(tmp_path, "a" * 40) == manifest
