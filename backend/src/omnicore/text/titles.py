"""One bounded, idle-priority title request using the conversation's existing engine."""

import asyncio

from omnicore.text.title_format import short_title
from omnicore.text.types import TextMessage


class Titles:
    def __init__(self, generations):
        self.generations = generations
        self.tasks = {}
        self.interrupt_lock = asyncio.Lock()

    def schedule(self, record):
        if not self.generations.closing and record.conversation_id not in self.tasks:
            self.tasks[record.conversation_id] = asyncio.create_task(self._generate(record))

    async def interrupt(self):
        async with self.interrupt_lock:
            tasks = list(self.tasks.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.tasks = {key: task for key, task in self.tasks.items() if not task.done()}

    async def _generate(self, record):
        manager = self.generations
        history = manager.history
        claimed, acquired = False, False
        engine = None
        state, title = "failed", None
        try:
            messages = await asyncio.to_thread(history.messages, record.conversation_id)
            answers = [m for m in messages if m.role == "assistant" and m.status == "completed"]
            if len(answers) != 1:
                return
            claim = asyncio.create_task(
                asyncio.to_thread(history.title_state, record.conversation_id, "generating")
            )
            try:
                claimed = await asyncio.shield(claim)
            except asyncio.CancelledError:
                claimed = await claim
                raise
            if not claimed:
                return
            # Never queue background title work in front of an answer.
            while manager.tasks:
                await asyncio.sleep(0.1)
            await manager.semaphore.acquire()
            acquired = True
            async with asyncio.timeout(15):
                settings = await asyncio.to_thread(history.history_settings)
                limit = settings["title_max_length"]
                model = await asyncio.to_thread(manager.store.model, record.model_id)
                engine = manager.engines[model.backend]
                parameters = record.parameters.model_copy(
                    update={
                        "max_tokens": 32,
                        "temperature": 0.2,
                        "thinking": False,
                        "system_prompt": "",
                    }
                )
                prompt = [
                    TextMessage(
                        role="user",
                        content=f"Only a topic title: 2–5 words, at most {limit} characters. "
                        "in the user's language. Do not answer the conversation.\n\n"
                        + "\n".join(m.content[:500] for m in messages[:2]),
                    )
                ]
                if model.backend == "llama.cpp":
                    path = manager.models.validated_reference(model.id)
                    with manager.models.policy.open(path) as stream:
                        await engine.load(path, parameters, file_descriptor=stream.fileno())
                        output = await self._consume(engine, str(path), prompt, parameters)
                else:
                    output = await self._consume(engine, model.location, prompt, parameters)
                title = short_title(output, limit)
                if title and not any(ord(c) < 32 for c in title) and "<" not in title:
                    state = "completed"
                else:
                    title = None
        except asyncio.CancelledError:
            state = "cancelled"
            if acquired and engine:
                await engine.unload(None)
            raise
        except Exception:
            if acquired and engine:
                await engine.unload(None)
        finally:
            if claimed:
                await asyncio.to_thread(history.title_state, record.conversation_id, state, title)
            if acquired:
                manager.semaphore.release()
            self.tasks.pop(record.conversation_id, None)

    @staticmethod
    async def _consume(engine, model, messages, parameters):
        output = ""
        async for chunk in engine.stream(model, messages, parameters):
            output += chunk.content
            if len(output) > 512:
                raise ValueError("Title output limit")
        return output
