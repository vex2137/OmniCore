"""Small transactional repository. Open a connection per operation."""

import os
import sqlite3
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from omnicore.schemas import Preferences

SCHEMA_VERSION = 1
MIGRATIONS = (files("omnicore").joinpath("migrations/001_preferences.sql").read_text(),)


def migrate(connection: sqlite3.Connection, migrations: tuple[str, ...] = MIGRATIONS) -> None:
    """All pending migrations commit together or roll back, including user_version."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > len(migrations):
            raise RuntimeError("Database schema is newer than this backend; refusing downgrade")
        for index in range(version, len(migrations)):
            # Migration files contain plain SQL statements, no triggers or embedded semicolons.
            # executescript() is deliberately avoided: it implicitly commits pending transactions.
            for statement in migrations[index].split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {index + 1}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


class Database:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "omnicore.sqlite3"

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ValueError("Database and data directory must not be symlinks")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self.connect() as connection:
            # Migrate before enabling WAL so newer databases are rejected without a journal change.
            migrate(connection)
            connection.execute("PRAGMA journal_mode = WAL")

    def version(self) -> int:
        with self.connect() as connection:
            # Check actual application data as well as the schema marker.
            row = connection.execute(
                "SELECT locale, theme, mode FROM preferences WHERE id = 1"
            ).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("Missing preferences row")
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def preferences(self) -> Preferences:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT locale, theme, mode FROM preferences WHERE id = 1"
            ).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("Missing preferences row")
            return Preferences(**dict(row))

    def save_preferences(self, preferences: Preferences) -> Preferences:
        with self.connect() as connection, connection:
            result = connection.execute(
                "UPDATE preferences SET locale = ?, theme = ?, mode = ? WHERE id = 1",
                (preferences.locale, preferences.theme, preferences.mode),
            )
            if result.rowcount != 1:
                raise sqlite3.DatabaseError("Missing preferences row")
        return preferences
