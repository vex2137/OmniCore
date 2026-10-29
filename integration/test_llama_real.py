"""Explicitly requested real GGUF test. No automatic download and no mock fallback."""

import os
import shutil
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.config import RuntimeConfig


@pytest.mark.parametrize("device", ["cpu", "auto"])
def test_gguf_without_ollama(tmp_path, device):
    executable = os.environ.get("OMNICORE_TEST_LLAMA_SERVER") or shutil.which("llama-server")
    model = os.environ.get("OMNICORE_TEST_GGUF")
    assert executable and Path(executable).is_file(), "Set OMNICORE_TEST_LLAMA_SERVER"
    assert model and Path(model).is_file(), "Set OMNICORE_TEST_GGUF to an existing compatible model"
    assert shutil.which("ollama") is None, "This scenario requires Ollama not to be installed"
    with httpx.Client(trust_env=False, timeout=1) as probe:
        try:
            probe.get("http://127.0.0.1:11434/api/version")
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("The no-Ollama scenario requires no server at localhost:11434")
    path = Path(model).absolute()
    app = create_app(
        RuntimeConfig(
            data_dir=tmp_path / "data",
            model_roots=(path.parent,),
            llama_server=Path(executable),
            llama_cuda_server=Path(os.environ["OMNICORE_TEST_LLAMA_CUDA_SERVER"])
            if os.environ.get("OMNICORE_TEST_LLAMA_CUDA_SERVER")
            else None,
            ollama_enabled=False,
            llama_chat_template=os.environ.get("OMNICORE_TEST_CHAT_TEMPLATE"),
            generation_timeout=120,
        )
    )
    with TestClient(app, base_url="http://localhost") as client:
        imported = client.post("/api/v1/text/models/import", json={"path": str(path)})
        assert imported.status_code == 201, imported.text
        model_id = imported.json()["id"]
        parameters = {
            "max_tokens": 24,
            "temperature": 0,
            "context_size": 512,
            "gpu_layers": 20 if device == "auto" else 0,
            "device": device,
        }
        loaded = client.post(f"/api/v1/text/models/{model_id}/load", json=parameters)
        assert loaded.status_code == 200, loaded.text
        process = app.state.text.llama.process
        assert process is not None and process.returncode is None
        conversation = client.post("/api/v1/text/conversations", json={"model_id": model_id}).json()
        response = client.post(
            f"/api/v1/text/conversations/{conversation['id']}/generations",
            json={
                "content": "Once upon a time",
                "request_key": "real-inference",
                "parameters": parameters,
            },
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 125
        while time.monotonic() < deadline:
            record = client.get(f"/api/v1/text/generations/{job_id}").json()
            if record["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.1)
        assert record["state"] == "completed", record
        assert record["content"].strip(), "The real model must generate actual text"
        assert record["model_name"] == imported.json()["name"]
        assert record["output_tokens"] > 0 and record["input_tokens"] > 0
        assert record["ttft_seconds"] > 0
        assert record["first_answer_seconds"] >= record["ttft_seconds"]
        assert record["generation_seconds"] >= record["first_answer_seconds"]
        assert record["context_used_tokens"] == record["input_tokens"] + record["output_tokens"]
        assert record["context_limit_tokens"] == 512
        assert record["finish_reason"] in {"stop", "length"}
        assert record["execution_device"] == app.state.text.llama.execution_device
        if device == "auto" and not app.state.text.llama.devices:
            assert record["execution_device"] == "cpu"
            assert record["fallback_reason"] == "gpu_unavailable"
        messages = client.get(f"/api/v1/text/conversations/{conversation['id']}/messages").json()
        assert messages[-1]["role"] == "assistant" and messages[-1]["content"] == record["content"]
        assert messages[-1]["model_name"] == record["model_name"]
        assert messages[-1]["statistics"]["output_tokens"] == record["output_tokens"]
        assert client.post(f"/api/v1/text/models/{model_id}/unload").status_code == 200
        assert app.state.text.llama.process is None and process.returncode is not None
