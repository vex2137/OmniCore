from dataclasses import replace

from fastapi.testclient import TestClient

from omnicore.app import create_app


def test_named_tokens_metadata_expiration_scopes_and_revoke_all(config):
    app = create_app(replace(config, api_token="a" * 64))
    owner = {"Authorization": "Bearer " + "a" * 64}
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234)) as c:
        result = c.post("/api/v1/access/tokens", headers=owner, json={"name": "POCO"})
        assert result.status_code == 200
        credential = result.json()
        token = {"Authorization": "Bearer " + credential["token"]}
        assert c.get("/api/v1/health", headers=token).status_code == 200
        records = c.get("/api/v1/access/tokens", headers=owner).json()
        assert len(records) == 1 and records[0]["name"] == "POCO"
        assert records[0]["last_used_at"] and records[0]["expires_at"] is None
        assert credential["token"] not in str(records)
        assert c.get("/api/v1/access/capabilities", headers=token).json()["scopes"] == ["chat"]
        assert (
            c.post("/api/v1/access/tokens", headers=token, json={"name": "No"}).status_code == 403
        )
        with app.state.db.connect() as connection, connection:
            assert (
                connection.execute("SELECT hash FROM lan_devices").fetchone()[0]
                != credential["token"]
            )
            connection.execute("UPDATE lan_token_info SET expires=0")
        assert c.get("/api/v1/health", headers=token).status_code == 401
        assert (
            c.request(
                "DELETE", "/api/v1/access/tokens", headers=owner, json={"confirmed": False}
            ).status_code
            == 422
        )
        assert len(c.get("/api/v1/access/tokens", headers=owner).json()) == 1
        assert (
            c.request(
                "DELETE", "/api/v1/access/tokens", headers=owner, json={"confirmed": True}
            ).status_code
            == 200
        )
        assert c.get("/api/v1/access/tokens", headers=owner).json() == []
        assert c.get("/api/v1/health", headers=owner).status_code == 200


def test_retry_bound_to_first_nonce_does_not_mint_or_revive_credentials(config):
    app = create_app(replace(config, api_token="a" * 64, allow_remote=True))
    owner = {"Authorization": "Bearer " + "a" * 64}
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234)) as c:
        offer = c.post("/api/v1/pairing/offers", headers=owner).json()
        request = {"code": offer["code"], "nonce": "b" * 64}
        credential = c.post("/api/v1/pairing/redeem", json=request).json()
        assert c.post("/api/v1/pairing/redeem", json=request).json() == credential
        assert (
            c.post("/api/v1/pairing/redeem", json={**request, "nonce": "c" * 64}).status_code == 403
        )
        assert c.post("/api/v1/pairing/redeem", json={"code": offer["code"]}).status_code == 403
        assert (
            c.get("/api/v1/pairing/offers/" + offer["id"], headers=owner).json()["status"] == "used"
        )
        c.delete("/api/v1/pairing/offers/" + offer["id"], headers=owner)
        c.post("/api/v1/pairing/offers", headers=owner)
        assert c.post("/api/v1/pairing/redeem", json=request).json() == credential
        assert len(c.get("/api/v1/access/tokens", headers=owner).json()) == 1
        c.delete("/api/v1/access/tokens/" + credential["device_id"], headers=owner)
        assert c.post("/api/v1/pairing/redeem", json=request).status_code == 403


def test_expired_nonce_retry_is_denied_by_server_clock(config):
    app = create_app(replace(config, api_token="a" * 64, allow_remote=True))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234)) as c:
        offer = app.state.pairings.create()
        app.state.pairings.redeem(offer.code, "127.0.0.1", "b" * 64)
        with app.state.db.connect() as connection, connection:
            connection.execute("UPDATE lan_pairing SET expires=0")
        response = c.post("/api/v1/pairing/redeem", json={"code": offer.code, "nonce": "b" * 64})
        assert response.status_code == 403 and response.json()["error"]["code"] == "pairing_expired"
