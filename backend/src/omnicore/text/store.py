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
                if version == 5 and len(TEXT_MIGRATIONS) == 3:
                    self._validate_v5(connection)
                    connection.commit()
                    return
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

    @staticmethod
    def _validate_v5(connection):
        # v4/v5 migrations are unavailable. Accept only the observed v5 layout,
        # and reject records we cannot round-trip without losing fields.
        from omnicore.text.conversations import Conversation, MessageRecord
        from omnicore.text.downloads import DownloadRecord
        from omnicore.text.generation import GenerationRecord

        required = {
            "text_models": ("id", "backend", "location", "record", "device", "inode"),
            "text_jobs": ("kind", "id", "record"),
            "text_conversations": ("id", "record"),
            "text_messages": ("seq", "id", "conversation_id", "generation_id", "record"),
            "text_generation_keys": ("request_key", "job_id", "fingerprint"),
            "text_history_settings": ("id", "auto_title", "title_max_length"),
            "ai_providers": ("id", "record"),
            "ai_retired_keys": ("reference",),
            "lan_devices": ("id", "hash", "created"),
            "lan_pairing": ("id", "hash", "expires", "nonce_hash", "device_id"),
            "lan_token_info": ("id", "name", "expires", "last_used", "scopes"),
        }
        for table, columns in required.items():
            actual = tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")'))
            if actual != columns:
                raise RuntimeError(f"Unsupported v5 schema: {table}")
        try:
            for query, model in (
                ("SELECT record FROM text_models", ModelRecord),
                ("SELECT record FROM text_conversations", Conversation),
                ("SELECT record FROM text_messages", MessageRecord),
            ):
                for row in connection.execute(query):
                    model.model_validate_json(row[0])
            for kind, model in (("download", DownloadRecord), ("generation", GenerationRecord)):
                for row in connection.execute("SELECT record FROM text_jobs WHERE kind=?", (kind,)):
                    model.model_validate_json(row[0])
        except ValueError as exc:
            raise RuntimeError("Unsupported v5 records; refusing to modify the database") from exc

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
        refresh_existing=False,
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
                "SELECT record,device,inode FROM text_models WHERE backend=? AND location=?",
                (backend, location),
            ).fetchone()
            if existing:
                previous = ModelRecord.model_validate_json(existing[0])
                changed = (device, inode) != (
                    existing[1],
                    existing[2],
                ) or size_bytes != previous.size_bytes
                old_mtime = previous.metadata.get("file_mtime_ns")
                changed |= old_mtime is not None and old_mtime != record.metadata.get(
                    "file_mtime_ns"
                )
                if not refresh_existing:
                    if backend == "llama.cpp" and device is not None and changed:
                        raise TextError("model_file_changed", 409)
                    return previous
                record.id, record.created_at = previous.id, previous.created_at
                record.parameters = previous.parameters
                if "desktop_context" in previous.metadata:
                    record.metadata["desktop_context"] = previous.metadata["desktop_context"]
                connection.execute(
                    "UPDATE text_models SET record=?,device=?,inode=? WHERE id=?",
                    (record.model_dump_json(), device, inode, record.id),
                )
                return record
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
