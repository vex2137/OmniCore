import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from omnicore.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_health_checks_database_and_contract(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0rc1", "database_version": 1}


def test_settings_persist_across_restarts(config):
    expected = {"schema_version": 1, "locale": "pl-PL", "theme": "dark", "mode": "advanced"}
    with TestClient(create_app(config), base_url="http://localhost") as client:
        assert client.put("/api/v1/settings", json=expected).json() == expected
    with TestClient(create_app(config), base_url="http://localhost") as client:
        assert client.get("/api/v1/settings").json() == expected


@pytest.mark.parametrize("theme", ["system", "light", "dark"])
def test_theme_preference_round_trip(client, theme):
    response = client.put("/api/v1/settings", json={"theme": theme})
    assert response.status_code == 200
    assert client.get("/api/v1/settings").json()["theme"] == theme


@pytest.mark.parametrize(
    "payload",
    [
        {"locale": "de-DE"},
        {"theme": "neon"},
        {"mode": "expert"},
        {"schema_version": 2},
        {"api_token": "must-never-be-reflected"},
        {"locale": None},
        [],
    ],
)
def test_invalid_preferences_do_not_mutate_database_or_echo_input(client, payload):
    original = client.get("/api/v1/settings").json()
    response = client.put("/api/v1/settings", json=payload, headers={"Accept-Language": "pl-PL"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "Nieprawidłowe" in response.json()["error"]["message"]
    assert "must-never-be-reflected" not in response.text
    assert client.get("/api/v1/settings").json() == original


def test_malformed_json_is_structured_error(client):
    response = client.put(
        "/api/v1/settings", content=b'{"theme":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_no_inference_is_advertised(client):
    assert client.get("/api/v1/backends").json() == []
    assert client.post("/api/v1/generate", json={}).status_code == 404


def test_database_failure_returns_503_without_path(client, app):
    with app.state.db.connect() as connection, connection:
        connection.execute("DROP TABLE preferences")
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert str(app.state.db.path) not in response.text


@pytest.mark.parametrize(
    ("method", "url", "status", "code"),
    [
        ("get", "/missing", 404, "not_found"),
        ("post", "/api/v1/settings", 405, "method_not_allowed"),
    ],
)
def test_http_errors(client, method, url, status, code):
    response = getattr(client, method)(url)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_openapi_and_json_schema_validate_real_responses(client):
    spec = client.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.1.")
    assert spec["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    for path in ["health", "settings", "locales", "locales/pl-PL", "backends"]:
        route = "/api/v1/" + path
        operation = spec["paths"][
            "/api/v1/locales/{locale}" if path.startswith("locales/") else route
        ]
        schema = operation["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        schema = {**schema, "components": spec["components"]}
        Draft202012Validator(schema).validate(client.get(route).json())
    schema = json.loads((ROOT / "contracts/Preferences.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(client.get("/api/v1/settings").json())


def test_unexpected_failure_has_structured_error_without_internal_details(app, monkeypatch):
    def failure():
        raise RuntimeError("private internal detail")

    monkeypatch.setattr(app.state.db, "version", failure)
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "private internal detail" not in response.text
