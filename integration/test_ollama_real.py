"""Optional real Ollama scenario; caller supplies an existing local model."""

import os
import time

from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.config import RuntimeConfig


def test_real_ollama_model(tmp_path):
    model = os.environ.get("OMNICORE_TEST_OLLAMA_MODEL")
    assert model, "Set OMNICORE_TEST_OLLAMA_MODEL; models are never downloaded by this test"
    app = create_app(
        RuntimeConfig(
            data_dir=tmp_path,
            ollama_url=os.environ.get("OMNICORE_TEST_OLLAMA_URL", "http://127.0.0.1:11434"),
        )
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/v1/text/models/sync-ollama")
        assert response.status_code == 200, response.text
        matches = [item for item in response.json() if item["name"] == model]
        assert matches, "The selected model is not present in Ollama"
        conversation = client.post(
            "/api/v1/text/conversations", json={"model_id": matches[0]["id"]}
        ).json()
        response = client.post(
            f"/api/v1/text/conversations/{conversation['id']}/generations",
            json={"content": "Say hello.", "request_key": "ollama-real"},
        )
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            record = client.get(f"/api/v1/text/generations/{response.json()['id']}").json()
            if record["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.1)
        assert record["state"] == "completed" and record["content"].strip(), record
        assert client.post(f"/api/v1/text/models/{matches[0]['id']}/unload").status_code == 200
