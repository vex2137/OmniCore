import time

from fastapi.testclient import TestClient
from test_text_api import create_chat, wait_job
from test_text_api import text_app as shared_text_app

text_app = shared_text_app


def wait_title(client, conversation_id, state):
    for _ in range(200):
        conversation = client.get(f"/api/v1/text/conversations/{conversation_id}").json()
        if conversation["title_status"] == state:
            return conversation
        time.sleep(0.01)
    raise AssertionError(conversation)


def test_auto_title_uses_existing_engine_once_and_manual_name_survives(text_app):
    app, path = text_app
    with TestClient(app, base_url="http://localhost") as c:
        model, _ = create_chat(c, path)
        chat = c.post("/api/v1/text/conversations", json={"model_id": model["id"]}).json()
        job = c.post(
            f"/api/v1/text/conversations/{chat['id']}/generations",
            json={"content": "Explain a forest", "request_key": "title-first"},
        ).json()
        assert wait_job(c, job["id"])["state"] == "completed"
        titled = wait_title(c, chat["id"], "completed")
        assert titled["title"] == "Hello world"  # Controlled adapter, not real model inference.
        c.patch(f"/api/v1/text/conversations/{chat['id']}", json={"title": "My title"})
        job = c.post(
            f"/api/v1/text/conversations/{chat['id']}/generations",
            json={"content": "Continue", "request_key": "title-second"},
        ).json()
        wait_job(c, job["id"])
        assert c.get(f"/api/v1/text/conversations/{chat['id']}").json()["title"] == "My title"


def test_title_disabled_and_manual_compare_and_set_preserve_history(text_app):
    app, path = text_app
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/api/v1/text/history/settings").json() == {"auto_title": True}
        assert c.put("/api/v1/text/history/settings", json={"auto_title": False}).status_code == 200
        model, _ = create_chat(c, path)
        chat = c.post("/api/v1/text/conversations", json={"model_id": model["id"]}).json()
        job = c.post(
            f"/api/v1/text/conversations/{chat['id']}/generations",
            json={"content": "Hello", "request_key": "disabled-title"},
        ).json()
        wait_job(c, job["id"])
        assert c.get(f"/api/v1/text/conversations/{chat['id']}").json()["title"] == ""
        c.put("/api/v1/text/history/settings", json={"auto_title": True})
        history = app.state.text.history
        race = history.create()
        assert history.title_state(race.id, "generating")
        history.update(race.id, title="Manual wins")
        assert not history.title_state(race.id, "completed", "Must not win")
        assert history.get(race.id).title == "Manual wins"


def test_bulk_delete_confirmation_count_and_active_generation_preserve_models(text_app):
    app, path = text_app
    with TestClient(app, base_url="http://localhost") as c:
        model, chat = create_chat(c, path)
        assert (
            c.request(
                "DELETE",
                "/api/v1/text/conversations",
                json={"confirmed": False, "expected_count": 1},
            ).status_code
            == 422
        )
        assert (
            c.request(
                "DELETE",
                "/api/v1/text/conversations",
                json={"confirmed": True, "expected_count": 2},
            ).status_code
            == 409
        )
        job = c.post(
            f"/api/v1/text/conversations/{chat['id']}/generations",
            json={"content": "hello", "request_key": "delete-active"},
        ).json()
        response = c.request(
            "DELETE", "/api/v1/text/conversations", json={"confirmed": True, "expected_count": 1}
        )
        assert response.status_code == 200 and response.json() == {"deleted": 1}
        assert not app.state.text.generations.tasks
        assert not app.state.text.generations.titles.tasks
        assert c.get("/api/v1/text/conversations").json() == []
        assert c.get(f"/api/v1/text/generations/{job['id']}").status_code == 404
        assert c.get(f"/api/v1/text/models/{model['id']}").status_code == 200
        assert path.exists()
        assert c.get("/api/v1/text/history/settings").json()["auto_title"]
        with app.state.db.connect() as connection:
            assert connection.execute("SELECT count(*) FROM text_messages").fetchone()[0] == 0
            assert (
                connection.execute("SELECT count(*) FROM text_generation_keys").fetchone()[0] == 0
            )
