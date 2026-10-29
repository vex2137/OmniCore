"""Text module schema versions share SQLite while preserving the core v1 contract."""

import json
import uuid
from datetime import UTC, datetime

from pydantic import Field

from omnicore.database import Database
from omnicore.schemas import ModelMetadata
from omnicore.text.types import TextError


def timestamp():
    return datetime.now(UTC).isoformat()


class ModelRecord(ModelMetadata):
    backend: str
    location: str
    capabilities: list[str] = Field(default_factory=list)
    compatibility: str = "unverified"
    metadata: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)
    created_at: str


TEXT_MIGRATIONS = (
    """
    CREATE TABLE text_models (
        id TEXT PRIMARY KEY, backend TEXT NOT NULL, location TEXT NOT NULL,
        record TEXT NOT NULL, device INTEGER, inode INTEGER,
        UNIQUE(backend, location)
    );
    """,
    """
    CREATE TABLE text_jobs (
        kind TEXT NOT NULL, id TEXT NOT NULL, record TEXT NOT NULL,
        PRIMARY KEY(kind,id)
    );
    """,
    """
    CREATE TABLE text_conversations (id TEXT PRIMARY KEY, record TEXT NOT NULL);
    CREATE TABLE text_messages (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        conversation_id TEXT NOT NULL REFERENCES text_conversations(id) ON DELETE CASCADE,
        generation_id TEXT UNIQUE, record TEXT NOT NULL
    );
    CREATE INDEX text_message_conversation ON text_messages(conversation_id,seq);
    CREATE TABLE text_generation_keys (
        request_key TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL
    );
    """,
)


class TextStore:
    def __init__(self, db: Database):
        self.db = db

    def initialize(self):
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS text_schema "
                    "(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)"
                )
                row = connection.execute("SELECT version FROM text_schema WHERE id=1").fetchone()
                version = row[0] if row else 0
                if version > len(TEXT_MIGRATIONS):
                    raise RuntimeError("Text schema is newer than this backend")
                for index in range(version, len(TEXT_MIGRATIONS)):
                    for statement in TEXT_MIGRATIONS[index].split(";"):
                        if statement.strip():
                            connection.execute(statement)
                connection.execute(
                    "INSERT INTO text_schema VALUES(1,?) "
                    "ON CONFLICT(id) DO UPDATE SET version=excluded.version",
                    (len(TEXT_MIGRATIONS),),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def add_model(
        self,
        *,
        backend,
        location,
        name,
        size_bytes,
        format,
        metadata=None,
        quantization=None,
        license=None,
        capabilities=None,
        device=None,
        inode=None,
    ):
        record = ModelRecord(
            id=uuid.uuid4().hex,
            backend=backend,
            location=location,
            name=name,
            size_bytes=size_bytes,
            format=format,
            metadata=metadata or {},
            quantization=quantization,
            license=license,
            capabilities=capabilities or [],
            created_at=timestamp(),
        )
        with self.db.connect() as connection, connection:
            existing = connection.execute(
                "SELECT record FROM text_models WHERE backend=? AND location=?", (backend, location)
            ).fetchone()
            if existing:
                return ModelRecord.model_validate_json(existing[0])
            connection.execute(
                "INSERT INTO text_models VALUES(?,?,?,?,?,?)",
                (record.id, backend, location, record.model_dump_json(), device, inode),
            )
        return record

    def model(self, model_id: str) -> ModelRecord:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT record FROM text_models WHERE id=?", (model_id,)
            ).fetchone()
        if row is None:
            raise TextError("not_found", 404)
        return ModelRecord.model_validate_json(row[0])

    def models(self, query="", backend="", format=""):
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM text_models ORDER BY rowid DESC"
            ).fetchall()
        records = [ModelRecord.model_validate_json(row[0]) for row in rows]
        return [
            r
            for r in records
            if query.lower() in r.name.lower()
            and (not backend or r.backend == backend)
            and (not format or r.format == format)
        ]

    def update_model(self, record: ModelRecord):
        with self.db.connect() as connection, connection:
            connection.execute(
                "UPDATE text_models SET record=? WHERE id=?", (record.model_dump_json(), record.id)
            )
        return record

    def delete_model(self, model_id):
        with self.db.connect() as connection, connection:
            connection.execute("DELETE FROM text_models WHERE id=?", (model_id,))

    def model_identity(self, model_id):
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT device,inode FROM text_models WHERE id=?", (model_id,)
            ).fetchone()
        if row is None:
            raise TextError("not_found", 404)
        return row[0], row[1]

    def save_job(self, kind: str, job_id: str, record: dict):
        with self.db.connect() as connection, connection:
            connection.execute(
                "INSERT INTO text_jobs VALUES(?,?,?) "
                "ON CONFLICT(kind,id) DO UPDATE SET record=excluded.record",
                (kind, job_id, json.dumps(record, ensure_ascii=False)),
            )

    def job(self, kind: str, job_id: str):
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT record FROM text_jobs WHERE kind=? AND id=?", (kind, job_id)
            ).fetchone()
        if row is None:
            raise TextError("not_found", 404)
        return json.loads(row[0])

    def jobs(self, kind: str):
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM text_jobs WHERE kind=? ORDER BY rowid DESC", (kind,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
