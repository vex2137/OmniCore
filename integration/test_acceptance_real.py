"""Actual packaged-tool backend flow on existing GGUF CPU, with no inference fixture."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from omnicore.hardware_acceptance import exercise


def test_acceptance_cpu_and_auto_are_isolated_from_existing_data(tmp_path, monkeypatch):
    model = Path(os.environ["OMNICORE_TEST_GGUF"]).resolve(strict=True)
    monkeypatch.setenv("OMNICORE_LLAMA_SERVER", os.environ["OMNICORE_TEST_LLAMA_SERVER"])
    persistent = tmp_path / "existing-data"
    persistent.mkdir()
    sentinel = persistent / "existing-history.json"
    sentinel.write_text('{"conversation":"preserve", "locale":"pl-PL"}')
    before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    model_time = model.stat().st_mtime_ns
    monkeypatch.setenv("OMNICORE_DATA_DIR", str(persistent))
    report = asyncio.run(exercise([model], ["cpu", "auto"], max_tokens=24, context=512))
    assert report["passed"] and not report["hardware_ready"]
    assert len(report["tests"]) == 2 and all(t["passed"] for t in report["tests"])
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before
    assert model.stat().st_mtime_ns == model_time
    serialized = json.dumps(report)
    assert "Bearer" not in serialized and "Authorization" not in serialized
    assert str(persistent) not in serialized and str(model.parent) not in serialized
