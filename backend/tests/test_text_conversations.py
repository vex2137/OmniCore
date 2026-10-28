import json

import pytest
from pydantic import ValidationError

from omnicore.database import Database
from omnicore.text.conversations import ConversationExport, Conversations
from omnicore.text.store import TextStore
from omnicore.text.types import GenerationParameters, TextError


@pytest.fixture
def history(tmp_path):
    db = Database(tmp_path)
    db.initialize()
    store = TextStore(db)
    store.initialize()
    return Conversations(store)


def test_conversations_roles_search_rename_model_switch_and_restart(history):
    record = history.create("Polska rozmowa", model_id="first-model")
    for role, text in [
        ("system", "Odpowiadaj po polsku"),
        ("user", "ŻÓŁW"),
        ("assistant", "Odpowiedź"),
    ]:
        history.add_message(record.id, role, text)
    history.update(record.id, title="Renamed", model_id="other-engine-model")
    assert len(history.messages(record.id)) == 3
    assert history.get(record.id).model_id == "other-engine-model"
    assert history.list("żółw")[0].id == record.id
    reopened = Conversations(history.store)
    assert len(reopened.messages(record.id)) == 3
    assert reopened.get(record.id).title == "Renamed"
    reopened.delete(record.id)
    assert reopened.list() == []
    with history.store.db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM text_messages").fetchone()[0] == 0


def test_export_import_preserves_content_time_parameters_without_id_collisions(history):
    record = history.create("Round trip", parameters=GenerationParameters(seed=42))
    message = history.add_message(record.id, "user", "Hello")
    history.save_assistant(record.id, "job1", "Partial", "cancelled", GenerationParameters(seed=42))
    exported = history.export(record.id)
    document = ConversationExport.model_validate_json(exported.model_dump_json())
    copied = history.import_json(document)
    assert copied.id != record.id
    assert copied.parameters.seed == 42
    messages = history.messages(copied.id)
    assert messages[0].content == message.content
    assert messages[0].created_at == message.created_at
    assert messages[0].id != message.id
    assert messages[1].content == "Partial" and messages[1].status == "cancelled"
    assert messages[1].generation_id is None


def test_assistant_updates_are_idempotent(history):
    record = history.create()
    for content, status in [("one", "running"), ("one two", "running"), ("one two", "completed")]:
        history.save_assistant(record.id, "job1", content, status, GenerationParameters())
    assert len(history.messages(record.id)) == 1
    assert history.messages(record.id)[0].content == "one two"
    assert history.messages(record.id)[0].status == "completed"


def test_import_rejects_unknown_fields_roles_and_missing_timezone(history):
    record = history.create()
    history.add_message(record.id, "user", "test")
    original = history.export(record.id).model_dump(mode="json")
    for key, value in [
        ("role", "unknown"),
        ("created_at", "not a timestamp"),
        ("created_at", "2026-10-28T10:00:00"),
    ]:
        document = json.loads(json.dumps(original))
        document["messages"][0][key] = value
        with pytest.raises(ValidationError):
            ConversationExport.model_validate(document)
    with pytest.raises(ValidationError):
        ConversationExport.model_validate({**original, "secret": "not allowed"})
    assert len(history.list()) == 1


def test_missing_conversation_is_404(history):
    for action in [history.get, history.messages, history.delete, history.export]:
        with pytest.raises(TextError, match="not_found"):
            action("missing")
