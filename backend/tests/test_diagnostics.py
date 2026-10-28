from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.config import RuntimeConfig


def test_readonly_diagnostics_are_authenticated_and_do_not_expose_configuration(tmp_path):
    token = "a" * 48
    config = RuntimeConfig(data_dir=tmp_path, api_token=token, ollama_enabled=False)
    with TestClient(create_app(config), base_url="http://localhost") as client:
        assert client.get("/api/v1/text/diagnostics").status_code == 401
        response = client.get(
            "/api/v1/text/diagnostics", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["hardware"]["disk_free_bytes"] > 0
        assert body["hardware"]["cpu_architecture"]
        assert body["generations"] == []
        assert token not in response.text
        assert str(tmp_path) not in response.text
