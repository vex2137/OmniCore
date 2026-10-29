import json

from omnicore.database import Database
from omnicore.schemas import Preferences
from omnicore.text.conversations import Conversations
from omnicore.text.store import TextStore


def test_alpha3_rows_preferences_catalog_and_export_survive_upgrade_without_rewrite(tmp_path):
    db = Database(tmp_path)
    db.initialize()
    db.save_preferences(Preferences(locale="pl-PL", theme="dark"))
    store = TextStore(db)
    store.initialize()
    model = store.add_model(
        backend="ollama",
        location="existing-model",
        name="Existing model",
        size_bytes=10,
        format="Ollama",
    )
    history = Conversations(store)
    conversation = history.create("Existing conversation", model_id=model.id)
    # Literal Alpha.3 shape before gpu_offloaded_layers existed.
    old = {
        "id": "old-message",
        "conversation_id": conversation.id,
        "role": "assistant",
        "content": "Saved answer",
        "status": "completed",
        "created_at": "2026-10-29T10:00:00+00:00",
        "model_id": model.id,
        "model_name": "Original name",
        "reasoning_content": "Separate thought",
        "statistics": {"output_tokens": 3, "finish_reason": "stop"},
    }
    original = json.dumps(old)
    with db.connect() as connection, connection:
        connection.execute(
            "INSERT INTO text_messages(id,conversation_id,record) VALUES(?,?,?)",
            (old["id"], conversation.id, original),
        )
    db.initialize()
    store.initialize()
    message = Conversations(TextStore(Database(tmp_path))).messages(conversation.id)[0]
    assert message.content == "Saved answer" and message.model_name == "Original name"
    assert message.reasoning_content == "Separate thought"
    assert message.statistics.gpu_offloaded_layers is None
    assert db.preferences().locale == "pl-PL" and db.preferences().theme == "dark"
    assert store.model(model.id).location == "existing-model"
    with db.connect() as connection:
        assert (
            connection.execute(
                "SELECT record FROM text_messages WHERE id=?", ("old-message",)
            ).fetchone()[0]
            == original
        )
    exported = history.export(conversation.id)
    copied = history.import_json(exported)
    assert history.messages(copied.id)[0].content == message.content
