import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.pairing import private_peer
from omnicore.text.types import TextError


@pytest.fixture
def pairing_app(config):
    return create_app(replace(config, allow_remote=True, api_token="a" * 64, lan_only=True))


def test_pair_exchange_single_use_hashes_restart_and_revocation(pairing_app):
    app = pairing_app
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234)) as client:
        master = {"Authorization": "Bearer " + "a" * 64}
        offer = client.post("/api/v1/pairing/offers", headers=master).json()
        assert time.time() < offer["expires_at"] <= time.time() + 120
        assert "a" * 64 not in str(offer)
        response = client.post("/api/v1/pairing/redeem", json={"code": offer["code"]})
        assert response.status_code == 200
        credential = response.json()
        paired = {"Authorization": "Bearer " + credential["token"]}
        assert client.get("/api/v1/health", headers=paired).status_code == 200
        assert client.post("/api/v1/pairing/offers", headers=paired).status_code == 403
        assert (
            client.post("/api/v1/pairing/redeem", json={"code": offer["code"]}).status_code == 403
        )
        with app.state.db.connect() as c:
            stored = c.execute("SELECT hash FROM lan_devices").fetchone()[0]
            assert stored != credential["token"]
        app.state.pairings.initialize()
        assert client.get("/api/v1/health", headers=paired).status_code == 200
        assert len(client.get("/api/v1/pairing/devices", headers=master).json()) == 1
        assert (
            client.delete(
                "/api/v1/pairing/devices/" + credential["device_id"], headers=master
            ).status_code
            == 200
        )
        assert client.get("/api/v1/health", headers=paired).status_code == 401


def test_expired_cancelled_wrong_and_restart_cancelled_offers(pairing_app):
    app = pairing_app
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234)) as client:
        headers = {"Authorization": "Bearer " + "a" * 64}
        offer = client.post("/api/v1/pairing/offers", headers=headers).json()
        assert client.post("/api/v1/pairing/redeem", json={"code": "b" * 64}).status_code == 403
        with app.state.db.connect() as c, c:
            c.execute("UPDATE lan_pairing SET expires=0")
        assert (
            client.post("/api/v1/pairing/redeem", json={"code": offer["code"]}).status_code == 403
        )
        for restart in [False, True]:
            offer = client.post("/api/v1/pairing/offers", headers=headers).json()
            if restart:
                app.state.pairings.initialize()
            else:
                assert (
                    client.delete(
                        "/api/v1/pairing/offers/" + offer["id"], headers=headers
                    ).status_code
                    == 200
                )
            assert (
                client.post("/api/v1/pairing/redeem", json={"code": offer["code"]}).status_code
                == 403
            )


def test_pairing_requires_auth_host_and_private_network(pairing_app):
    app = pairing_app
    with TestClient(app, base_url="http://localhost", client=("192.168.1.20", 1234)) as client:
        assert client.get("/api/v1/health").status_code == 401
        assert (
            client.get("/api/v1/health", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/pairing/offers", headers={"Authorization": "Bearer " + "a" * 64}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/pairing/redeem",
                headers={"Host": "attacker.example"},
                json={"code": "b" * 64},
            ).status_code
            == 403
        )
    with TestClient(app, base_url="http://localhost", client=("8.8.8.8", 1234)) as client:
        assert (
            client.get(
                "/api/v1/health", headers={"Authorization": "Bearer " + "a" * 64}
            ).status_code
            == 403
        )


def test_concurrent_redemption_only_grants_one_device_and_limits_guesses(pairing_app):
    with TestClient(pairing_app, base_url="http://localhost", client=("127.0.0.1", 1234)):
        pairings = pairing_app.state.pairings
        offer = pairings.create()

        def redeem(_):
            try:
                pairings.redeem(offer.code, "192.168.1.20")
                return True
            except TextError:
                return False

        with ThreadPoolExecutor(max_workers=4) as pool:
            assert sum(pool.map(redeem, range(4))) == 1
        for _ in range(10):
            try:
                pairings.redeem("b" * 64, "192.168.1.21")
            except TextError as exc:
                assert exc.status == 403
        with pytest.raises(TextError, match="pairing_rate_limited"):
            pairings.redeem("b" * 64, "192.168.1.21")


@pytest.mark.parametrize(
    "address,allowed",
    [
        ("192.168.1.2", True),
        ("10.1.2.3", True),
        ("172.31.2.3", True),
        ("127.0.0.1", True),
        ("8.8.8.8", False),
        ("169.254.1.2", False),
        ("172.32.1.2", False),
        ("example.org", False),
    ],
)
def test_private_peers_are_explicit(address, allowed):
    assert private_peer(address) is allowed
