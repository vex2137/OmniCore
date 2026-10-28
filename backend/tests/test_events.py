import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from omnicore.events import EventHub
from omnicore.schemas import Preferences, ServerEvent


def test_websocket_hello_ping_and_settings_fanout(client, app):
    with client.websocket_connect("ws://localhost/api/v1/events") as first:
        assert first.receive_json() == {
            "schema_version": 1,
            "type": "hello",
            "settings": Preferences().model_dump(mode="json"),
        }
        with client.websocket_connect("ws://localhost/api/v1/events") as second:
            assert second.receive_json()["type"] == "hello"
            first.send_json({"type": "ping"})
            assert first.receive_json()["type"] == "pong"
            response = client.put("/api/v1/settings", json={"locale": "pl-PL", "theme": "light"})
            assert response.status_code == 200
            for websocket in [first, second]:
                event = websocket.receive_json()
                assert event["type"] == "settings.updated"
                assert event["settings"] == response.json()
    assert not app.state.hub.subscribers


def test_invalid_websocket_payload_is_error_and_connection_remains_usable(client):
    with client.websocket_connect(
        "ws://localhost/api/v1/events", headers={"Accept-Language": "pl"}
    ) as websocket:
        websocket.receive_json()
        for payload in ["not json", '{"type":"generate"}', '{"type":"ping","extra":true}']:
            websocket.send_text(payload)
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["error"]["code"] == "validation_error"
            assert "Nieprawidłowe" in error["error"]["message"]
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json()["type"] == "pong"


@pytest.mark.parametrize(("binary", "expected_code"), [(True, 1003), (False, 1009)])
def test_websocket_rejects_binary_and_oversized_messages(client, binary, expected_code):
    with client.websocket_connect("ws://localhost/api/v1/events") as websocket:
        websocket.receive_json()
        if binary:
            websocket.send_bytes(b"binary")
        else:
            websocket.send_text("x" * 65_537)
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == expected_code


def test_slow_event_consumers_have_bounded_memory_and_keep_latest_snapshot():
    async def exercise():
        hub = EventHub()
        with hub.subscribe() as queue:
            for _ in range(100):
                hub.publish(ServerEvent(type="pong"))
            hub.publish(ServerEvent(type="settings.updated", settings=Preferences(theme="dark")))
            assert queue.qsize() == 32
            last = None
            while not queue.empty():
                last = await queue.get()
            assert last.settings.theme == "dark"
        assert not hub.subscribers

    asyncio.run(exercise())


def test_websocket_database_failure_is_explicit_and_cleans_subscription(client, app):
    with app.state.db.connect() as connection, connection:
        connection.execute("DROP TABLE preferences")
    with client.websocket_connect("ws://localhost/api/v1/events") as websocket:
        assert websocket.receive_json()["error"]["code"] == "database_unavailable"
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1011
    assert not app.state.hub.subscribers
