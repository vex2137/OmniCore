"""Explicit public HF test: real metadata, cancel/resume, checksum and catalog import."""

import time

from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.config import RuntimeConfig

REPOSITORY = "bartowski/SmolLM2-135M-Instruct-GGUF"
FILENAME = "SmolLM2-135M-Instruct-Q4_K_M.gguf"
SHA256 = "2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d"


def test_real_public_download_cancel_resume_checksum_import(tmp_path):
    with TestClient(
        create_app(RuntimeConfig(data_dir=tmp_path, ollama_enabled=False)),
        base_url="http://localhost",
    ) as client:
        response = client.get("/api/v1/text/huggingface/files", params={"repository": REPOSITORY})
        assert response.status_code == 200, response.text
        file = next(f for f in response.json() if f["filename"] == FILENAME)
        assert file["sha256"] == SHA256 and file["size_bytes"] == 105454432
        response = client.post(
            "/api/v1/text/downloads",
            json={
                "repository": REPOSITORY,
                "filename": FILENAME,
                "revision": file["revision"],
                "confirmed": True,
                "expected_size": file["size_bytes"],
            },
        )
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            record = client.get(f"/api/v1/text/downloads/{identifier}").json()
            if record["received_bytes"] > 0 or record["state"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert record["state"] != "failed", record
        cancelled = client.post(f"/api/v1/text/downloads/{identifier}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        if cancelled.json()["state"] != "completed":
            assert client.post(f"/api/v1/text/downloads/{identifier}/resume").status_code == 200
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            record = client.get(f"/api/v1/text/downloads/{identifier}").json()
            if record["state"] in {"completed", "failed"}:
                break
            time.sleep(0.2)
        assert record["state"] == "completed" and record["integrity_verified"], record
        imported = client.post("/api/v1/text/models/import", json={"path": record["path"]})
        assert imported.status_code == 201, imported.text
        assert imported.json()["backend"] == "llama.cpp"
        assert imported.json()["compatibility"] == "unverified"
