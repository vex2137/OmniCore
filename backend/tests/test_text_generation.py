import asyncio

import pytest
from test_text_models import synthetic_gguf

from omnicore.database import Database
from omnicore.events import EventHub
from omnicore.schemas import BackendInfo
from omnicore.text.conversations import Conversations
from omnicore.text.files import FilePolicy
from omnicore.text.generation import GenerationManager, GenerationRequest
from omnicore.text.models import ModelManager
from omnicore.text.store import TextStore
from omnicore.text.types import TextChunk, TextError


class ProtocolTestEngine:
    """Controlled transport behavior, not a real model or inference test."""

    def __init__(self, *, wait=False, error=None, available=True):
        self.wait, self.error, self.available = wait, error, available
        self.unloaded = False
        self.started = asyncio.Event()

    async def probe(self):
        return BackendInfo(id="llama.cpp", version="protocol-test", available=self.available)

    async def load(self, path, parameters, file_descriptor=None):
        assert file_descriptor is not None

    async def stream(self, model, messages, parameters):
        assert any(message.role == "user" for message in messages)
        yield TextChunk(content="Hello")
        self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        if self.error:
            raise TextError(self.error, 503)
        yield TextChunk(content=" world", output_tokens=2, tokens_per_second=1)

    async def unload(self, model=None):
        self.unloaded = True

    async def stop(self):
        await self.unload()


def create_manager(tmp_path, engine, timeout=3):
    db = Database(tmp_path / "data")
    db.initialize()
    store = TextStore(db)
    store.initialize()
    root = tmp_path / "models"
    root.mkdir(exist_ok=True)
    path = root / "fixture.gguf"
    path.write_bytes(synthetic_gguf())
    models = ModelManager(store, FilePolicy((root,)))
    model = models.import_gguf(path)
    manager = GenerationManager(store, models, {"llama.cpp": engine}, EventHub(), timeout=timeout)
    conversation = manager.history.create(model_id=model.id)
    return manager, conversation


def test_success_idempotency_and_persistent_reply(tmp_path):
    async def exercise():
        manager, conversation = create_manager(tmp_path, ProtocolTestEngine())
        request = GenerationRequest(content="hello", request_key="once")
        record = await manager.submit(conversation.id, request)
        task = manager.tasks[record.id]  # Keep the handle before duplicate submission yields.
        duplicate = await manager.submit(conversation.id, request)
        assert duplicate.id == record.id
        await task
        result = manager.record(record.id)
        assert result.state == "completed" and result.content == "Hello world"
        assert result.output_tokens == 2 and result.tokens_per_second == 1
        messages = manager.history.messages(conversation.id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[-1].content == result.content and messages[-1].status == "completed"
        assert (await manager.submit(conversation.id, request)).id == record.id
        assert len(manager.history.messages(conversation.id)) == 2
        assert manager.store.model(result.model_id).compatibility == "tested"
        with pytest.raises(TextError, match="idempotency_conflict"):
            await manager.submit(
                conversation.id, GenerationRequest(content="different", request_key="once")
            )
        await manager.close()

    asyncio.run(exercise())


def test_cancel_partial_generation_and_queued_job(tmp_path):
    async def exercise():
        engine = ProtocolTestEngine(wait=True)
        manager, conversation = create_manager(tmp_path, engine)
        record = await manager.submit(
            conversation.id, GenerationRequest(content="hi", request_key="first")
        )
        await asyncio.wait_for(engine.started.wait(), 2)
        with pytest.raises(TextError, match="conversation_busy"):
            await manager.submit(
                conversation.id, GenerationRequest(content="hi", request_key="another")
            )
        second = manager.history.create(model_id=record.model_id)
        queued = await manager.submit(
            second.id, GenerationRequest(content="hi", request_key="second")
        )
        assert queued.state == "queued"
        await manager.cancel(queued.id)
        assert manager.record(queued.id).state == "cancelled"
        await manager.cancel(record.id)
        result = manager.record(record.id)
        assert result.state == "cancelled" and result.content == "Hello"
        assert manager.history.messages(conversation.id)[-1].status == "cancelled"
        assert engine.unloaded
        await manager.cancel(record.id)
        await manager.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("wait", "error", "expected"),
    [
        (True, None, "engine_timeout"),
        (False, "out_of_memory", "out_of_memory"),
        (False, "engine_stream_interrupted", "engine_stream_interrupted"),
    ],
)
def test_failure_preserves_partial_history(tmp_path, wait, error, expected):
    async def exercise():
        manager, conversation = create_manager(
            tmp_path, ProtocolTestEngine(wait=wait, error=error), timeout=3
        )
        record = await manager.submit(
            conversation.id, GenerationRequest(content="hi", request_key="failure")
        )
        await manager.tasks[record.id]
        result = manager.record(record.id)
        assert result.state == "failed" and result.error_code == expected
        assert result.content == "Hello"
        assert manager.history.messages(conversation.id)[-1].status == "failed"
        await manager.close()

    asyncio.run(exercise())


def test_missing_engine_is_explicit_failure_and_not_supported_model(tmp_path):
    async def exercise():
        manager, conversation = create_manager(tmp_path, ProtocolTestEngine(available=False))
        record = await manager.submit(
            conversation.id, GenerationRequest(content="hi", request_key="missing")
        )
        await manager.tasks[record.id]
        assert manager.record(record.id).error_code == "engine_unavailable"
        assert manager.store.model(record.model_id).compatibility == "unverified"
        await manager.close()

    asyncio.run(exercise())


def test_restart_marks_durable_running_job_interrupted(tmp_path):
    async def exercise():
        manager, conversation = create_manager(tmp_path, ProtocolTestEngine())
        record = await manager.submit(
            conversation.id, GenerationRequest(content="hi", request_key="restart")
        )
        await manager.tasks[record.id]
        saved = manager.record(record.id)
        saved.state = "running"
        manager.store.save_job("generation", saved.id, saved.model_dump(mode="json"))
        restarted = GenerationManager(manager.store, manager.models, {}, EventHub())
        restarted.initialize()
        assert restarted.record(saved.id).state == "interrupted"
        assert Conversations(manager.store).messages(conversation.id)[-1].content == "Hello world"
        await manager.close()

    asyncio.run(exercise())
