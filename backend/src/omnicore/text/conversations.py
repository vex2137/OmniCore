import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from omnicore.schemas import WireModel
from omnicore.text.store import TextStore, timestamp
from omnicore.text.types import GenerationParameters, GenerationStatistics, TextError


class Conversation(WireModel):
    id: str
    title: str = Field(default="", max_length=256)
    model_id: str | None = None
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)
    created_at: str
    updated_at: str
    # Missing fields in old history are manual: never replace a pre-existing title.
    title_status: Literal[
        "manual", "pending", "generating", "completed", "failed", "cancelled", "interrupted"
    ] = "manual"


class MessageRecord(WireModel):
    id: str
    conversation_id: str
    role: Literal["system", "user", "assistant"]
    content: str = Field(default="", max_length=1_000_000)
    status: Literal["completed", "running", "cancelled", "failed", "interrupted"] = "completed"
    created_at: str
    generation_id: str | None = None
    parameters: GenerationParameters | None = None
    model_id: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=1024)
    reasoning_content: str = Field(default="", max_length=1_000_000)
    statistics: GenerationStatistics | None = None

    @field_validator("created_at")
    @classmethod
    def validate_timestamp(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Timestamp requires a timezone")
        return parsed.astimezone(UTC).isoformat()


class ConversationExport(WireModel):
    schema_version: Literal[1] = 1
    title: str = Field(max_length=256)
    model_id: str | None = None
    parameters: GenerationParameters
    messages: list[MessageRecord] = Field(max_length=10000)


class Conversations:
    def __init__(self, store: TextStore):
        self.store = store

    def create(self, title="", model_id=None, parameters=None):
        conversation = Conversation(
            id=uuid.uuid4().hex,
            title=title,
            model_id=model_id,
            parameters=parameters or GenerationParameters(),
            created_at=timestamp(),
            updated_at=timestamp(),
            title_status="pending" if not title else "manual",
        )
        with self.store.db.connect() as connection, connection:
            connection.execute(
                "INSERT INTO text_conversations VALUES(?,?)",
                (conversation.id, conversation.model_dump_json()),
            )
        return conversation

    def get(self, conversation_id):
        with self.store.db.connect() as connection:
            row = connection.execute(
                "SELECT record FROM text_conversations WHERE id=?", (conversation_id,)
            ).fetchone()
        if row is None:
            raise TextError("not_found", 404)
        return Conversation.model_validate_json(row[0])

    def list(self, query=""):
        with self.store.db.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM text_conversations ORDER BY rowid DESC"
            ).fetchall()
        records = [Conversation.model_validate_json(row[0]) for row in rows]
        if not query:
            return records
        result = []
        for record in records:
            if query.casefold() in record.title.casefold() or self.messages(record.id, query):
                result.append(record)
        return result

    def update(self, conversation_id, **changes):
        with self.store.db.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record FROM text_conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if row is None:
                raise TextError("not_found", 404)
            record = Conversation.model_validate_json(row[0]).model_dump()
            if "title" in changes:
                changes["title_status"] = "manual"
            record.update(changes, updated_at=timestamp())
            updated = Conversation.model_validate(record)
            connection.execute(
                "UPDATE text_conversations SET record=? WHERE id=?",
                (updated.model_dump_json(), conversation_id),
            )
        return updated

    def history_settings(self):
        with self.store.db.connect() as c:
            row = c.execute("SELECT auto_title FROM text_history_settings WHERE id=1").fetchone()
        return {"auto_title": bool(row[0])}

    def save_history_settings(self, enabled):
        with self.store.db.connect() as c, c:
            c.execute("UPDATE text_history_settings SET auto_title=? WHERE id=1", (enabled,))
        return self.history_settings()

    def title_state(self, conversation_id, status, title=None):
        """Compare-and-set protects manual renames while a title is being generated."""
        with self.store.db.connect() as c, c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT record FROM text_conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not row:
                return False
            record = Conversation.model_validate_json(row[0])
            expected = "pending" if status == "generating" else "generating"
            if record.title_status != expected:
                return False
            enabled = c.execute(
                "SELECT auto_title FROM text_history_settings WHERE id=1"
            ).fetchone()[0]
            record.title_status = status if enabled else "cancelled"
            if title and enabled:
                record.title = title
            record.updated_at = timestamp()
            c.execute(
                "UPDATE text_conversations SET record=? WHERE id=?",
                (record.model_dump_json(), conversation_id),
            )
            return bool(enabled)

    def delete_all(self, expected_count):
        with self.store.db.connect() as c, c:
            c.execute("BEGIN IMMEDIATE")
            count = c.execute("SELECT count(*) FROM text_conversations").fetchone()[0]
            if count != expected_count:
                raise TextError("history_changed", 409)
            c.execute("DELETE FROM text_generation_keys")
            c.execute("DELETE FROM text_jobs WHERE kind='generation'")
            c.execute("DELETE FROM text_conversations")
        return count

    def delete(self, conversation_id):
        self.get(conversation_id)
        with self.store.db.connect() as connection, connection:
            connection.execute("DELETE FROM text_conversations WHERE id=?", (conversation_id,))

    def messages(self, conversation_id, query=""):
        self.get(conversation_id)
        with self.store.db.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM text_messages WHERE conversation_id=? ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        records = [MessageRecord.model_validate_json(row[0]) for row in rows]
        return [record for record in records if query.casefold() in record.content.casefold()]

    def add_message(self, conversation_id, role, content, **extra):
        self.get(conversation_id)
        record = MessageRecord(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=timestamp(),
            **extra,
        )
        with self.store.db.connect() as connection, connection:
            connection.execute(
                "INSERT INTO text_messages(id,conversation_id,generation_id,record) "
                "VALUES(?,?,?,?)",
                (record.id, conversation_id, record.generation_id, record.model_dump_json()),
            )
        return record

    def save_assistant(
        self, conversation_id, generation_id, content, status, parameters, **metadata
    ):
        with self.store.db.connect() as connection, connection:
            previous = connection.execute(
                "SELECT record FROM text_messages WHERE generation_id=?", (generation_id,)
            ).fetchone()
            if previous:
                record = MessageRecord.model_validate_json(previous[0])
                record = record.model_copy(
                    update={"content": content, "status": status, **metadata}
                )
                connection.execute(
                    "UPDATE text_messages SET record=? WHERE generation_id=?",
                    (record.model_dump_json(), generation_id),
                )
            else:
                record = MessageRecord(
                    id=uuid.uuid4().hex,
                    conversation_id=conversation_id,
                    generation_id=generation_id,
                    role="assistant",
                    content=content,
                    status=status,
                    parameters=parameters,
                    created_at=timestamp(),
                    **metadata,
                )
                connection.execute(
                    "INSERT INTO text_messages(id,conversation_id,generation_id,record) "
                    "VALUES(?,?,?,?)",
                    (record.id, conversation_id, generation_id, record.model_dump_json()),
                )
        return record

    def export(self, conversation_id):
        record = self.get(conversation_id)
        return ConversationExport(
            title=record.title,
            model_id=record.model_id,
            parameters=record.parameters,
            messages=self.messages(conversation_id),
        )

    def import_json(self, document: ConversationExport):
        # New IDs prevent overwriting unrelated history; content, timestamps and parameters survive.
        record = Conversation(
            id=uuid.uuid4().hex,
            title=document.title,
            model_id=document.model_id,
            parameters=document.parameters,
            created_at=timestamp(),
            updated_at=timestamp(),
        )
        with self.store.db.connect() as connection, connection:
            connection.execute(
                "INSERT INTO text_conversations VALUES(?,?)", (record.id, record.model_dump_json())
            )
            for original in document.messages:
                imported = original.model_copy(
                    update={
                        "id": uuid.uuid4().hex,
                        "conversation_id": record.id,
                        "generation_id": None,
                        "status": "interrupted"
                        if original.status == "running"
                        else original.status,
                    }
                )
                connection.execute(
                    "INSERT INTO text_messages(id,conversation_id,generation_id,record) "
                    "VALUES(?,?,NULL,?)",
                    (imported.id, record.id, imported.model_dump_json()),
                )
        return record
