from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from omnicore.app import create_app
from omnicore.config import RuntimeConfig

TOKEN = "testTokenForAuthenticationOnly12345"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "backend.example"])
def test_remote_binding_requires_explicit_opt_in(tmp_path, host):
    with pytest.raises(ValueError, match="ALLOW_REMOTE"):
        RuntimeConfig(data_dir=tmp_path, host=host)


@pytest.mark.parametrize("token", [None, "short"])
def test_remote_opt_in_requires_strong_token(tmp_path, token):
    with pytest.raises(ValueError, match="API_TOKEN"):
        RuntimeConfig(data_dir=tmp_path, host="0.0.0.0", allow_remote=True, api_token=token)


@pytest.mark.parametrize(
    "origin", ["*", "https://*.example", "ftp://example", "https://example/path"]
)
def test_invalid_cors_origins_are_rejected(config, origin):
    with pytest.raises(ValueError, match="CORS"):
        replace(config, allowed_origins=(origin,))


def test_runtime_config_from_environment_and_token_not_in_repr(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNICORE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OMNICORE_HOST", "0.0.0.0")
    monkeypatch.setenv("OMNICORE_ALLOW_REMOTE", "1")
    monkeypatch.setenv("OMNICORE_API_TOKEN", TOKEN)
    monkeypatch.setenv("OMNICORE_ALLOWED_ORIGINS", "https://ui.example")
    config = RuntimeConfig.from_env()
    assert config.host == "0.0.0.0"
    assert config.allowed_origins == ("https://ui.example",)
    assert TOKEN not in repr(config)


def test_rest_authentication_and_cors(config):
    config = replace(
        config,
        host="0.0.0.0",
        allow_remote=True,
        api_token=TOKEN,
        allowed_origins=("https://ui.example",),
    )
    with TestClient(create_app(config), base_url="http://localhost") as client:
        assert client.get("/api/v1/health").status_code == 401
        assert client.get("/openapi.json").status_code == 401
        assert client.get("/api/v1/health", headers={"Authorization": TOKEN}).status_code == 401
        assert (
            client.get("/api/v1/health", headers={"Authorization": "Bearer incorrect"}).status_code
            == 401
        )
        auth = {"Authorization": f"Bearer {TOKEN}"}
        response = client.get("/api/v1/health", headers={**auth, "Origin": "https://ui.example"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://ui.example"
        assert TOKEN not in response.text
        assert (
            client.get(
                "/api/v1/health", headers={**auth, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        response = client.options(
            "/api/v1/settings",
            headers={
                "Origin": "https://ui.example",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://ui.example"


def test_websocket_authentication_and_origin(config):
    config = replace(
        config, allow_remote=True, api_token=TOKEN, allowed_origins=("https://ui.example",)
    )
    with TestClient(create_app(config), base_url="http://localhost") as client:
        with (
            pytest.raises(WebSocketDisconnect) as error,
            client.websocket_connect("ws://localhost/api/v1/events"),
        ):
            pass
        assert error.value.code == 4401
        with (
            pytest.raises(WebSocketDisconnect) as error,
            client.websocket_connect(
                "ws://localhost/api/v1/events",
                headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://evil.example"},
            ),
        ):
            pass
        assert error.value.code == 4403
        with client.websocket_connect(
            "ws://localhost/api/v1/events",
            headers={"Origin": "https://ui.example"},
            subprotocols=["omnicore.v1", f"bearer.{TOKEN}"],
        ) as websocket:
            assert websocket.accepted_subprotocol == "omnicore.v1"
            assert websocket.receive_json()["type"] == "hello"


def test_body_size_limit_uses_received_bytes_not_content_length(client):
    response = client.put(
        "/api/v1/settings",
        content=b"x" * 65_537,
        headers={"Content-Length": "1", "Accept-Language": "pl"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert "przekracza" in response.json()["error"]["message"]
    assert client.get("/api/v1/settings").json()["theme"] == "system"


def test_cross_origin_mutation_is_rejected_by_default(client):
    assert (
        client.put(
            "/api/v1/settings", json={"theme": "dark"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/settings").json()["theme"] == "system"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "[broken"])
def test_unapproved_host_is_rejected_even_without_origin(client, host):
    response = client.get("/api/v1/settings", headers={"Host": host})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_host"


def test_explicit_remote_hostname_is_allowed(config):
    config = replace(
        config,
        host="0.0.0.0",
        allow_remote=True,
        api_token=TOKEN,
        allowed_hosts=("my-backend.example",),
    )
    with TestClient(create_app(config), base_url="https://my-backend.example") as client:
        assert (
            client.get("/api/v1/health", headers={"Authorization": f"Bearer {TOKEN}"}).status_code
            == 200
        )
