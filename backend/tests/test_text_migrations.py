import sqlite3

import pytest

import omnicore.text.store as store_module
from omnicore.database import Database
from omnicore.schemas import Preferences
from omnicore.text.store import TextStore


def test_text_upgrade_preserves_core_preferences_and_models(tmp_path, monkeypatch):
    db = Database(tmp_path)
    db.initialize()
    db.save_preferences(Preferences(locale="pl-PL", theme="dark"))
    migrations = store_module.TEXT_MIGRATIONS
    monkeypatch.setattr(store_module, "TEXT_MIGRATIONS", migrations[:1])
    store = TextStore(db)
    store.initialize()
    model = store.add_model(
        backend="ollama", location="test", name="test", size_bytes=1, format="Ollama"
    )
    monkeypatch.setattr(store_module, "TEXT_MIGRATIONS", migrations)
    store.initialize()
    assert store.model(model.id) == model
    assert db.preferences().locale == "pl-PL" and db.preferences().theme == "dark"
    assert db.version() == 1
    with db.connect() as connection:
        assert connection.execute("SELECT version FROM text_schema").fetchone()[0] == len(
            migrations
        )


def test_failed_text_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    db = Database(tmp_path)
    db.initialize()
    store = TextStore(db)
    store.initialize()
    previous = len(store_module.TEXT_MIGRATIONS)
    monkeypatch.setattr(
        store_module,
        "TEXT_MIGRATIONS",
        store_module.TEXT_MIGRATIONS + ("CREATE TABLE must_rollback (id INTEGER); INVALID SQL;",),
    )
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()
    with db.connect() as connection:
        assert connection.execute("SELECT version FROM text_schema").fetchone()[0] == previous
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='must_rollback'"
            ).fetchone()
            is None
        )


def test_v5_history_round_trip_and_backup(tmp_path):
    import json

    from omnicore.text.conversations import Conversations

    db = Database(tmp_path)
    db.initialize()
    store = TextStore(db)
    store.initialize()
    history = Conversations(store)
    conversation = history.create(title="Saved")
    message = history.add_message(conversation.id, "assistant", "Hello")
    with db.connect() as connection, connection:
        data = json.loads(connection.execute("SELECT record FROM text_conversations").fetchone()[0])
        data["title_status"] = "completed"
        connection.execute("UPDATE text_conversations SET record=?", (json.dumps(data),))
        data = json.loads(connection.execute("SELECT record FROM text_messages").fetchone()[0])
        data["statistics"] = {"execution_provider": "local", "execution_model": "model"}
        connection.execute("UPDATE text_messages SET record=?", (json.dumps(data),))
        for sql in (
            "CREATE TABLE text_history_settings (id, auto_title, title_max_length)",
            "CREATE TABLE ai_providers (id, record)",
            "CREATE TABLE ai_retired_keys (reference)",
            "CREATE TABLE lan_devices (id, hash, created)",
            "CREATE TABLE lan_pairing (id, hash, expires, nonce_hash, device_id)",
            "CREATE TABLE lan_token_info (id, name, expires, last_used, scopes)",
        ):
            connection.execute(sql)
        connection.execute("UPDATE text_schema SET version=5")
    db.initialize()
    store.initialize()
    assert history.list()[0].title_status == "completed"
    assert history.messages(conversation.id)[0].statistics.execution_model == "model"
    history.update(conversation.id, title="New")
    with db.connect() as connection:
        assert connection.execute("SELECT version FROM text_schema").fetchone()[0] == 5
        assert (
            json.loads(connection.execute("SELECT record FROM text_conversations").fetchone()[0])[
                "title_status"
            ]
            == "completed"
        )
        assert connection.execute("SELECT id FROM text_messages").fetchone()[0] == message.id
    backups = list(tmp_path.glob("omnicore-backup-*.sqlite3"))
    assert backups
    with sqlite3.connect(backups[-1]) as backup:
        assert backup.execute("SELECT version FROM text_schema").fetchone()[0] == 5
        assert (
            json.loads(backup.execute("SELECT record FROM text_conversations").fetchone()[0])[
                "title"
            ]
            == "Saved"
        )


def test_v5_unknown_schema_is_rejected_without_downgrade(tmp_path):
    db = Database(tmp_path)
    db.initialize()
    store = TextStore(db)
    store.initialize()
    with db.connect() as connection, connection:
        connection.execute("UPDATE text_schema SET version=5")
    with pytest.raises(RuntimeError, match="Unsupported v5 schema"):
        store.initialize()
    with db.connect() as connection:
        assert connection.execute("SELECT version FROM text_schema").fetchone()[0] == 5
