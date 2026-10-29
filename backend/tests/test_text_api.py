import hashlib
import socket
import threading
import time
from dataclasses import replace

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from test_text_generation import ProtocolTestEngine
from test_text_models import synthetic_gguf

from omnicore.app import create_app
from omnicore.text.downloads import RemoteFile


@pytest.fixture
def text_app(config, tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    path = root / "test.gguf"
    path.write_bytes(synthetic_gguf())
    config = replace(config, model_roots=(root,), ollama_enabled=False)
    app = create_app(config)
    app.state.text.engines["llama.cpp"] = ProtocolTestEngine()
    return app, path


def wait_job(client, job_id, state=None, prefix="generations"):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        record = client.get(f"/api/v1/text/{prefix}/{job_id}").json()
        if (
            record["state"] == state
            or state is None
            and record["state"] in {"completed", "failed", "cancelled", "interrupted"}
        ):
            return record
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach expected state: {record}")


def create_chat(client, path):
    model = client.post("/api/v1/text/models/import", json={"path": str(path)})
    assert model.status_code == 201, model.text
    conversation = client.post(
        "/api/v1/text/conversations", json={"title": "Test", "model_id": model.json()["id"]}
    )
    assert conversation.status_code == 201, conversation.text
    return model.json(), conversation.json()


def test_complete_text_api_without_real_inference(text_app):
    app, path = text_app
    with TestClient(app, base_url="http://localhost") as client:
        model, conversation = create_chat(client, path)
        assert (
            client.get("/api/v1/text/models", params={"query": "fixture"}).json()[0]["id"]
            == model["id"]
        )
        response = client.post(
            f"/api/v1/text/conversations/{conversation['id']}/generations",
            json={"content": "Hi", "request_key": "api-once"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        record = wait_job(client, job_id)
        assert record["state"] == "completed" and record["content"] == "Hello world"
        response = client.get(f"/api/v1/text/generations/{job_id}/stream")
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"state": "completed"' in response.text
        messages = client.get(f"/api/v1/text/conversations/{conversation['id']}/messages").json()
        assert [m["role"] for m in messages] == ["user", "assistant"]
        document = client.get(f"/api/v1/text/conversations/{conversation['id']}/export").json()
        copied = client.post("/api/v1/text/conversations/import", json=document)
        assert copied.status_code == 201 and copied.json()["id"] != conversation["id"]
        assert len(client.get("/api/v1/text/conversations", params={"query": "Hello"}).json()) == 2
        assert (
            client.patch(
                f"/api/v1/text/conversations/{conversation['id']}",
                json={"title": "Renamed", "model_id": None},
            ).status_code
            == 200
        )
        assert (
            client.request("DELETE", f"/api/v1/text/models/{model['id']}", json={}).status_code
            == 200
        )
        assert path.exists()


def test_path_security_and_confirmation_errors_are_localized(text_app):
    app, path = text_app
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/v1/text/models/import",
            json={"path": "/etc/passwd"},
            headers={"Accept-Language": "pl"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "invalid_path"
        assert "Ścieżka" in response.json()["error"]["message"]
        assert (
            client.post(
                "/api/v1/text/downloads",
                json={"repository": "test/model", "filename": "test.gguf", "expected_size": 10},
            ).status_code
            == 409
        )
        assert client.post("/api/v1/text/models/sync-ollama").status_code == 503
        _, conversation = create_chat(client, path)
        assert (
            client.patch(
                f"/api/v1/text/conversations/{conversation['id']}", json={"title": None}
            ).status_code
            == 422
        )


def test_new_endpoints_preserve_authentication_and_do_not_expose_hf_token(config):
    secret = "privateTestValueNotAProductionCredential1234"
    config = replace(config, allow_remote=True, api_token=secret, hf_token=secret)
    assert secret not in repr(config)
    with TestClient(create_app(config), base_url="http://localhost") as client:
        for path in ["models", "engines", "conversations", "downloads", "generations/missing"]:
            response = client.get("/api/v1/text/" + path)
            assert response.status_code == 401 and secret not in response.text
        response = client.get("/api/v1/text/status", headers={"Authorization": f"Bearer {secret}"})
        assert response.status_code == 200 and secret not in response.text
        assert response.json()["generation_concurrency"] == 1


def test_model_defaults_and_generation_parameter_validation(text_app):
    app, path = text_app
    with TestClient(app, base_url="http://localhost") as client:
        model, _ = create_chat(client, path)
        assert (
            client.put(
                f"/api/v1/text/models/{model['id']}/parameters", json={"seed": 123}
            ).status_code
            == 200
        )
        conversation = client.post(
            "/api/v1/text/conversations", json={"model_id": model["id"]}
        ).json()
        assert conversation["parameters"]["seed"] == 123
        for parameters in [
            {"top_p": 2},
            {"gpu_layers": -1},
            {"context_size": 0},
            {"max_tokens": 0},
        ]:
            response = client.post(
                f"/api/v1/text/conversations/{conversation['id']}/generations",
                json={"content": "hi", "request_key": "invalid", "parameters": parameters},
            )
            assert response.status_code == 422
        assert client.get(f"/api/v1/text/conversations/{conversation['id']}/messages").json() == []


def test_websocket_disconnect_cancels_explicitly_watched_generation(text_app):
    app, path = text_app
    app.state.text.engines["llama.cpp"] = ProtocolTestEngine(wait=True)
    with TestClient(app, base_url="http://localhost") as client:
        _, conversation = create_chat(client, path)
        job = client.post(
            f"/api/v1/text/conversations/{conversation['id']}/generations",
            json={"content": "hi", "request_key": "ws-cancel"},
        ).json()
        wait_job(client, job["id"], "running")
        with client.websocket_connect("ws://localhost/api/v1/events") as websocket:
            assert websocket.receive_json()["type"] == "hello"
            websocket.send_json(
                {"type": "generation.watch", "job_id": job["id"], "cancel_on_disconnect": True}
            )
            assert websocket.receive_json()["type"] == "generation.updated"
        assert wait_job(client, job["id"])["state"] == "cancelled"
        assert client.get("/api/v1/health").status_code == 200


def test_hf_download_endpoints_with_controlled_transport(text_app, monkeypatch):
    app, _ = text_app
    hub = app.state.text.downloads.hub
    payload = synthetic_gguf()
    source = RemoteFile(
        repository="test/model",
        filename="test.gguf",
        revision="a" * 40,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )

    async def files(*args):
        return [source]

    monkeypatch.setattr(hub, "files", files)
    hub.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/v1/text/downloads",
            json={
                "repository": "test/model",
                "filename": "test.gguf",
                "expected_size": len(payload),
                "confirmed": True,
            },
        )
        assert response.status_code == 202
        record = wait_job(client, response.json()["id"], prefix="downloads")
        assert record["state"] == "completed" and record["integrity_verified"]
        assert (
            client.post("/api/v1/text/models/import", json={"path": record["path"]}).status_code
            == 201
        )


def test_sse_disconnect_cancels_with_real_http_connection(text_app):
    app, path = text_app
    app.state.text.engines["llama.cpp"] = ProtocolTestEngine(wait=True)
    # A real socket is required: an in-process ASGI client buffers streaming responses.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=3
        ) as client:
            deadline = time.monotonic() + 4
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            _, conversation = create_chat(client, path)
            job = client.post(
                f"/api/v1/text/conversations/{conversation['id']}/generations",
                json={"content": "hi", "request_key": "sse-cancel"},
            ).json()
            with client.stream("GET", f"/api/v1/text/generations/{job['id']}/stream") as response:
                assert response.status_code == 200
                assert next(response.iter_lines()).startswith("data:")
            result = wait_job(client, job["id"])
            assert result["state"] == "cancelled"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    assert not thread.is_alive()


def test_independent_clients_share_history_detach_and_cancel(text_app):
    """Two real HTTP transports with a protocol engine, not real inference."""
    import json

    app, path = text_app
    app.state.text.engines["llama.cpp"] = ProtocolTestEngine(wait=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        with (
            httpx.Client(base_url=base, trust_env=False, timeout=5) as linux,
            httpx.Client(base_url=base, trust_env=False, timeout=5) as android,
        ):
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            model, conversation = create_chat(linux, path)
            cid = conversation["id"]
            assert any(c["id"] == cid for c in android.get("/api/v1/text/conversations").json())
            job = android.post(
                f"/api/v1/text/conversations/{cid}/generations",
                json={"content": "shared request", "request_key": "shared-clients"},
            ).json()
            route = f"/api/v1/text/generations/{job['id']}"
            wait_job(linux, job["id"], "running")
            with linux.stream("GET", route + "/stream?cancel_on_disconnect=false") as stream:
                assert stream.status_code == 200
                assert next(stream.iter_lines()).startswith("data:")
            assert android.get(route).json()["state"] == "running"
            # The busy conversation/model cannot be changed under the other client.
            assert linux.delete(f"/api/v1/text/conversations/{cid}").status_code == 409
            assert (
                linux.patch(f"/api/v1/text/conversations/{cid}", json={"title": "race"}).status_code
                == 409
            )
            assert (
                linux.put(f"/api/v1/text/models/{model['id']}/parameters", json={}).status_code
                == 409
            )
            with linux.stream("GET", route + "/stream?cancel_on_disconnect=false") as stream:
                iterator = stream.iter_lines()
                assert next(iterator).startswith("data:")
                assert android.post(route + "/cancel").json()["state"] == "cancelled"
                records = [json.loads(line[6:]) for line in iterator if line.startswith("data:")]
                assert records[-1]["state"] == "cancelled"
                assert all(
                    a["sequence"] <= b["sequence"]
                    for a, b in zip(records, records[1:], strict=False)
                )
            history = linux.get(f"/api/v1/text/conversations/{cid}/messages").json()
            assert history == android.get(f"/api/v1/text/conversations/{cid}/messages").json()
            assert history[-1]["status"] == "cancelled" and history[-1]["content"] == "Hello"
            assert len([m for m in history if m["role"] == "user"]) == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    assert not thread.is_alive()
