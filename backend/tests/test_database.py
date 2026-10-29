import sqlite3
import stat

import pytest

from omnicore.database import MIGRATIONS, SCHEMA_VERSION, Database, migrate
from omnicore.schemas import Preferences


def test_fresh_database_and_repeatable_initialization(tmp_path):
    db = Database(tmp_path / "data")
    db.initialize()
    assert db.version() == SCHEMA_VERSION
    assert db.preferences() == Preferences()
    expected = Preferences(locale="pl-PL", theme="dark", mode="advanced")
    db.save_preferences(expected)
    db.initialize()
    assert Database(tmp_path / "data").preferences() == expected
    assert stat.S_IMODE(db.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.path.parent.stat().st_mode) == 0o700


def test_migration_preserves_existing_preferences():
    with sqlite3.connect(":memory:") as connection:
        migrate(connection)
        connection.execute("UPDATE preferences SET locale='pl-PL', theme='dark'")
        connection.commit()
        migrate(connection, MIGRATIONS + ("CREATE TABLE audit (id INTEGER PRIMARY KEY);",))
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT locale, theme FROM preferences").fetchone() == (
            "pl-PL",
            "dark",
        )


def test_failed_migration_rolls_back_ddl_data_and_version():
    with sqlite3.connect(":memory:") as connection:
        migrate(connection)
        with pytest.raises(sqlite3.OperationalError):
            migrate(
                connection,
                MIGRATIONS
                + (
                    "CREATE TABLE should_rollback (id INTEGER);"
                    "UPDATE preferences SET locale='pl-PL';"
                    "INVALID SQL;",
                ),
            )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT locale FROM preferences").fetchone()[0] == "en-US"
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='should_rollback'"
        ).fetchall()


def test_future_schema_is_rejected_without_rewriting_file(tmp_path):
    db = Database(tmp_path)
    with sqlite3.connect(db.path) as connection:
        connection.execute("PRAGMA user_version=99")
    original = db.path.read_bytes()
    with pytest.raises(RuntimeError, match="newer"):
        db.initialize()
    assert db.path.read_bytes() == original


def test_corrupt_database_is_not_replaced(tmp_path):
    db = Database(tmp_path)
    db.path.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        db.initialize()
    assert db.path.read_bytes() == b"not a sqlite database"


@pytest.mark.parametrize("target", ["directory", "database"])
def test_symlinks_are_rejected(tmp_path, target):
    data = tmp_path / "data"
    if target == "directory":
        real = tmp_path / "real"
        real.mkdir()
        data.symlink_to(real, target_is_directory=True)
    else:
        data.mkdir()
        real = tmp_path / "other.sqlite3"
        real.touch()
        (data / "omnicore.sqlite3").symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        Database(data).initialize()


def test_missing_preferences_is_not_silently_saved(config):
    db = Database(config.data_dir)
    db.initialize()
    with db.connect() as connection, connection:
        connection.execute("DELETE FROM preferences")
    for operation in [db.preferences, db.version, lambda: db.save_preferences(Preferences())]:
        with pytest.raises(sqlite3.DatabaseError):
            operation()
