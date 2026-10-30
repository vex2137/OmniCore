import asyncio

import pytest
from test_text_generation import ProtocolTestEngine, create_manager

from omnicore.text.generation import GenerationRequest
from omnicore.text.types import TextChunk, TextError


class TitleEngine(ProtocolTestEngine):
    def __init__(self, *, fail=False):
        super().__init__()
        self.title_started = asyncio.Event()
        self.fail_title = fail

    async def stream(self, model, messages, parameters):
        if parameters.max_tokens == 32:
            self.title_started.set()
            if self.fail_title:
                raise TextError("engine_unavailable", 503)
            await asyncio.Event().wait()
        yield TextChunk(content="Answer")


def test_title_is_preempted_by_next_answer_and_does_not_restart(tmp_path):
    async def exercise():
        engine = TitleEngine()
        manager, conversation = create_manager(tmp_path, engine)
        try:
            first = await manager.submit(
                conversation.id, GenerationRequest(content="First", request_key="title-a")
            )
            await manager.tasks[first.id]
            await asyncio.wait_for(engine.title_started.wait(), timeout=2)
            assert manager.record(first.id).state == "completed"
            next_record = await asyncio.wait_for(
                manager.submit(
                    conversation.id, GenerationRequest(content="Second", request_key="title-b")
                ),
                timeout=1,
            )
            await manager.tasks[next_record.id]
            assert manager.record(next_record.id).state == "completed"
            assert manager.history.get(conversation.id).title_status == "cancelled"
        finally:
            await manager.close()

    asyncio.run(exercise())


def test_failed_title_preserves_answer_and_restart_marks_interrupted(tmp_path):
    async def exercise():
        manager, conversation = create_manager(tmp_path, TitleEngine(fail=True))
        try:
            record = await manager.submit(
                conversation.id, GenerationRequest(content="First", request_key="title-fail")
            )
            await manager.tasks[record.id]
            await asyncio.gather(*list(manager.titles.tasks.values()))
            assert manager.history.get(conversation.id).title_status == "failed"
            assert manager.record(record.id).content == "Answer"
            interrupted = manager.history.create()
            assert manager.history.title_state(interrupted.id, "generating")
            manager.initialize()
            assert manager.history.get(interrupted.id).title_status == "interrupted"
        finally:
            await manager.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("title", ["New conversation", "Nowa rozmowa", "My manual title"])
def test_nonempty_creation_titles_are_always_manual(tmp_path, title):
    manager, _ = create_manager(tmp_path, ProtocolTestEngine())
    conversation = manager.history.create(title)
    assert not manager.history.title_state(conversation.id, "generating")
    assert manager.history.get(conversation.id).title == title
