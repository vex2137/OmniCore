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
