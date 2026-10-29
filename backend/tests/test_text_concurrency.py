"""Controlled scheduling regressions; no claim of real model inference."""

import asyncio

import pytest
from test_text_generation import ProtocolTestEngine, create_manager

from omnicore.text.generation import GenerationRequest


class CleanupEngine(ProtocolTestEngine):
    def __init__(self, error=None):
        super().__init__(wait=error is None, error=error)
        self.cleanup_started = asyncio.Event()
        self.release_cleanup = asyncio.Event()
        self.loads = 0
        self.overlap = False
        self.cleaning = False

    async def load(self, *args, **kwargs):
        self.loads += 1
        self.overlap |= self.cleaning
        await super().load(*args, **kwargs)

    async def unload(self, model=None):
        self.cleaning = True
        self.cleanup_started.set()
        await self.release_cleanup.wait()
        self.cleaning = False
        await super().unload(model)


@pytest.mark.parametrize("failure", [None, "out_of_memory", "engine_stream_interrupted"])
def test_queue_waits_for_previous_engine_cleanup(tmp_path, failure):
    async def exercise():
        engine = CleanupEngine(error=failure)
        manager, conversation = create_manager(tmp_path, engine)
        first = await manager.submit(
            conversation.id, GenerationRequest(content="first", request_key="a")
        )
        await asyncio.wait_for(engine.started.wait(), 5)
        other = manager.history.create(model_id=first.model_id)
        second = await manager.submit(
            other.id, GenerationRequest(content="second", request_key="b")
        )
        second_task = manager.tasks[second.id]
        cancellation = asyncio.create_task(manager.cancel(first.id)) if failure is None else None
        await asyncio.wait_for(engine.cleanup_started.wait(), 5)
        # Semaphore ownership is observable without relying on a wall-clock sleep.
        assert manager.semaphore.locked()
        assert manager.record(second.id).state == "queued"
        assert engine.loads == 1
        engine.wait = False
        engine.error = None
        engine.release_cleanup.set()
        if cancellation:
            await cancellation
        await asyncio.wait_for(second_task, 5)
        assert not engine.overlap
        assert manager.record(second.id).state == "completed"
        assert manager.record(second.id).content == "Hello world"
        assert manager.record(first.id).state == ("cancelled" if failure is None else "failed")
        await manager.close()

    asyncio.run(exercise())


def test_two_clients_cancel_once_without_interrupting_cleanup(tmp_path):
    async def exercise():
        engine = CleanupEngine()
        manager, conversation = create_manager(tmp_path, engine)
        record = await manager.submit(
            conversation.id, GenerationRequest(content="hello", request_key="once")
        )
        await asyncio.wait_for(engine.started.wait(), 5)
        first = asyncio.create_task(manager.cancel(record.id))
        await asyncio.wait_for(engine.cleanup_started.wait(), 5)
        second = asyncio.create_task(manager.cancel(record.id))
        engine.release_cleanup.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert {r.state for r in results} == {"cancelled"}
        assert manager.record(record.id).content == "Hello"
        assert not manager.semaphore.locked()
        assert manager.history.messages(conversation.id)[-1].status == "cancelled"
        await manager.close()

    asyncio.run(exercise())


def test_disconnect_of_cancel_request_does_not_abandon_engine_cleanup(tmp_path):
    async def exercise():
        engine = CleanupEngine()
        manager, conversation = create_manager(tmp_path, engine)
        record = await manager.submit(
            conversation.id, GenerationRequest(content="hello", request_key="request")
        )
        await asyncio.wait_for(engine.started.wait(), 5)
        caller = asyncio.create_task(manager.cancel(record.id))
        await asyncio.wait_for(engine.cleanup_started.wait(), 5)
        caller.cancel()
        engine.release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not manager.semaphore.locked()
        assert manager.record(record.id).state == "cancelled"
        await manager.close()

    asyncio.run(exercise())
