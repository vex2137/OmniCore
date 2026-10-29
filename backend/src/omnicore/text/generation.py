"""Durable, bounded generation jobs. Stream snapshots are never the only copy."""

import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Literal

from pydantic import Field

from omnicore.schemas import ServerEvent, WireModel
from omnicore.text.conversations import Conversations, MessageRecord
from omnicore.text.models import ModelManager
from omnicore.text.store import TextStore, timestamp
from omnicore.text.types import GenerationParameters, GenerationStatistics, TextError, TextMessage

TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


class GenerationRecord(GenerationStatistics):
    id: str
    conversation_id: str
    model_id: str
    state: Literal["queued", "running", "completed", "cancelled", "failed", "interrupted"] = (
        "queued"
    )
    parameters: GenerationParameters
    model_name: str | None = Field(default=None, max_length=1024)
    content: str = ""
    reasoning_content: str = Field(default="", max_length=1_000_000)
    sequence: int = 0
    error_code: str | None = None
    created_at: str
    updated_at: str


class GenerationRequest(WireModel):
    content: str = Field(min_length=1, max_length=60000)
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    model_id: str | None = None
    parameters: GenerationParameters | None = None


class GenerationManager:
    def __init__(
        self, store: TextStore, models: ModelManager, engines: dict, hub, timeout: float = 300
    ):
        self.store, self.models, self.engines, self.hub = store, models, engines, hub
        self.history = Conversations(store)
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(1)
        self.submission_lock = asyncio.Lock()
        self.cancellation_lock = asyncio.Lock()
        self.tasks: dict[str, asyncio.Task] = {}

    def record(self, job_id):
        return GenerationRecord.model_validate(self.store.job("generation", job_id))

    def _save(self, record):
        record.updated_at = timestamp()
        record.sequence += 1
        self.store.save_job("generation", record.id, record.model_dump(mode="json"))
        self.hub.publish(
            ServerEvent(type="generation.updated", task=record.model_dump(mode="json"))
        )

    def initialize(self):
        for item in self.store.jobs("generation"):
            if item["state"] not in TERMINAL:
                record = GenerationRecord.model_validate(item)
                record.state, record.error_code = "interrupted", "backend_restarted"
                self.store.save_job("generation", record.id, record.model_dump(mode="json"))
                self.history.save_assistant(
                    record.conversation_id,
                    record.id,
                    record.content,
                    "interrupted",
                    record.parameters,
                    model_id=record.model_id,
                    model_name=record.model_name,
                    reasoning_content=record.reasoning_content,
                    statistics=GenerationStatistics(
                        **{key: getattr(record, key) for key in GenerationStatistics.model_fields}
                    ),
                )

    def active_for(self, *, model_id=None, conversation_id=None):
        return any(
            (model_id is None or self.record(job_id).model_id == model_id)
            and (conversation_id is None or self.record(job_id).conversation_id == conversation_id)
            and self.record(job_id).state not in TERMINAL
            for job_id in list(self.tasks)
        )

    async def submit(self, conversation_id, request: GenerationRequest):
        async with self.submission_lock:
            conversation = await asyncio.to_thread(self.history.get, conversation_id)
            model_id = request.model_id or conversation.model_id
            if not model_id:
                raise TextError("model_required", 422)
            model = await asyncio.to_thread(self.store.model, model_id)
            parameters = request.parameters or conversation.parameters
            parameter_fingerprint = parameters.model_dump()
            # Preserve idempotency keys created by Alpha.1/2 before thinking was a field.
            if not parameters.thinking:
                parameter_fingerprint.pop("thinking")
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "conversation": conversation_id,
                        "model": model_id,
                        "content": request.content,
                        "parameters": parameter_fingerprint,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()

            def reserve():
                with self.store.db.connect() as connection, connection:
                    connection.execute("BEGIN IMMEDIATE")
                    previous = connection.execute(
                        "SELECT job_id,fingerprint FROM text_generation_keys WHERE request_key=?",
                        (request.request_key,),
                    ).fetchone()
                    if previous:
                        if previous[1] != fingerprint:
                            raise TextError("idempotency_conflict", 409)
                        return previous[0], False
                    if self.active_for(conversation_id=conversation_id):
                        raise TextError("conversation_busy", 409)
                    if len(self.tasks) >= 16:
                        raise TextError("queue_full", 429)
                    record = GenerationRecord(
                        id=uuid.uuid4().hex,
                        conversation_id=conversation_id,
                        model_id=model_id,
                        model_name=model.name,
                        context_limit_tokens=parameters.context_size,
                        parameters=parameters,
                        created_at=timestamp(),
                        updated_at=timestamp(),
                    )
                    user = MessageRecord(
                        id=uuid.uuid4().hex,
                        conversation_id=conversation_id,
                        role="user",
                        content=request.content,
                        model_id=model_id,
                        model_name=model.name,
                        created_at=timestamp(),
                    )
                    connection.execute(
                        "INSERT INTO text_generation_keys VALUES(?,?,?)",
                        (request.request_key, record.id, fingerprint),
                    )
                    connection.execute(
                        "INSERT INTO text_jobs VALUES('generation',?,?)",
                        (record.id, record.model_dump_json()),
                    )
                    connection.execute(
                        "INSERT INTO text_messages(id,conversation_id,record) VALUES(?,?,?)",
                        (user.id, conversation_id, user.model_dump_json()),
                    )
                    return record.id, True

            job_id, created = await asyncio.to_thread(reserve)
            if created:
                await asyncio.to_thread(
                    self.history.update, conversation_id, model_id=model_id, parameters=parameters
                )
                self.tasks[job_id] = asyncio.create_task(self._run(job_id))
            return self.record(job_id)

    async def _persist(self, record):
        record.updated_at = timestamp()
        record.sequence += 1
        snapshot = record.model_copy(deep=True)

        def commit_snapshot():
            with self.store.db.connect() as connection, connection:
                row = connection.execute(
                    "SELECT record FROM text_messages WHERE generation_id=?", (snapshot.id,)
                ).fetchone()
                message = (
                    MessageRecord.model_validate_json(row[0])
                    if row
                    else MessageRecord(
                        id=uuid.uuid4().hex,
                        conversation_id=snapshot.conversation_id,
                        role="assistant",
                        generation_id=snapshot.id,
                        created_at=timestamp(),
                    )
                )
                message.content, message.status = snapshot.content, snapshot.state
                message.parameters = snapshot.parameters
                message.model_id, message.model_name = snapshot.model_id, snapshot.model_name
                message.reasoning_content = snapshot.reasoning_content
                message.statistics = GenerationStatistics(
                    **{key: getattr(snapshot, key) for key in GenerationStatistics.model_fields}
                )
                connection.execute(
                    "INSERT INTO text_messages(id,conversation_id,generation_id,record) "
                    "VALUES(?,?,?,?) "
                    "ON CONFLICT(generation_id) DO UPDATE SET record=excluded.record",
                    (
                        message.id,
                        message.conversation_id,
                        message.generation_id,
                        message.model_dump_json(),
                    ),
                )
                connection.execute(
                    "UPDATE text_jobs SET record=? WHERE kind='generation' AND id=?",
                    (snapshot.model_dump_json(), snapshot.id),
                )

        writer = asyncio.create_task(asyncio.to_thread(commit_snapshot))
        try:
            await asyncio.shield(writer)
        except asyncio.CancelledError:
            await writer
            raise
        self.hub.publish(
            ServerEvent(type="generation.updated", task=snapshot.model_dump(mode="json"))
        )

    async def _run(self, job_id):
        record = self.record(job_id)
        engine = None
        unload_name = None
        acquired = False
        started = None
        try:
            await self.semaphore.acquire()
            acquired = True
            started = time.monotonic()
            async with asyncio.timeout(self.timeout):
                record.state = "running"
                await self._persist(record)
                model = await asyncio.to_thread(self.store.model, record.model_id)
                unload_name = model.location if model.backend == "ollama" else None
                engine = self.engines.get(model.backend)
                engine_info = await engine.probe() if engine else None
                if engine_info is None or not engine_info.available:
                    raise TextError("engine_unavailable", 503)
                history = await asyncio.to_thread(self.history.messages, record.conversation_id)
                messages = [
                    TextMessage(role=item.role, content=item.content)
                    for item in history
                    if item.role != "assistant" or item.status == "completed"
                ]
                if record.parameters.system_prompt:
                    messages.insert(
                        0, TextMessage(role="system", content=record.parameters.system_prompt)
                    )
                if model.backend == "llama.cpp":
                    # The child inherits the validated descriptor, so replacing a pathname cannot
                    # swap in a different model between validation and llama-server opening it.
                    path = self.models.validated_reference(model.id)
                    with self.models.policy.open(path) as stream:
                        info = os.fstat(stream.fileno())
                        if (info.st_dev, info.st_ino) != self.store.model_identity(model.id):
                            raise TextError("model_file_changed", 409)
                        loading = time.monotonic()
                        try:
                            await engine.load(
                                path, record.parameters, file_descriptor=stream.fileno()
                            )
                        finally:
                            record.model_load_seconds = time.monotonic() - loading
                        await self._consume(engine, str(path), messages, record, started)
                else:
                    await self._consume(engine, model.location, messages, record, started)
                if record.content.strip():
                    model.compatibility = "tested"
                    model.capabilities = list(
                        dict.fromkeys([*model.capabilities, "text-generation"])
                    )
                    model.tested_backends = list(
                        dict.fromkeys([*model.tested_backends, model.backend])
                    )
                    model.metadata["last_inference"] = {
                        "at": timestamp(),
                        "engine_version": engine_info.version,
                        "device": record.parameters.device
                        if model.backend == "llama.cpp"
                        else "engine-managed",
                    }
                    await asyncio.to_thread(self.store.update_model, model)
                else:
                    raise TextError(
                        "reasoning_limit_reached"
                        if record.reasoning_content and record.finish_reason == "length"
                        else "empty_response",
                        502,
                    )
                record.state = "completed"
                record.generation_seconds = time.monotonic() - started
                record.finish_reason = record.finish_reason or "stop"
                await self._persist(record)
        except asyncio.CancelledError:
            record.state, record.error_code = "cancelled", None
            record.finish_reason = "cancelled"
            record.generation_seconds = time.monotonic() - started if started is not None else None
            await self._persist(record)
            if engine:
                await engine.unload(unload_name)
            raise
        except TimeoutError:
            record.state, record.error_code = "failed", "engine_timeout"
            record.generation_seconds = time.monotonic() - started if started is not None else None
            record.finish_reason = record.finish_reason or "error"
            await self._persist(record)
            if engine:
                await engine.unload(unload_name)
        except TextError as exc:
            record.state, record.error_code = "failed", exc.code
            record.generation_seconds = time.monotonic() - started if started is not None else None
            record.finish_reason = record.finish_reason or "error"
            await self._persist(record)
            if engine:
                await engine.unload(unload_name)
        except Exception:
            record.state, record.error_code = "failed", "generation_failed"
            record.generation_seconds = time.monotonic() - started if started is not None else None
            record.finish_reason = record.finish_reason or "error"
            await self._persist(record)
            if engine:
                await engine.unload(unload_name)
        finally:
            # Cleanup owns the same engine as inference. A queued client must not load it
            # while cancellation/error handling is still unloading the previous model.
            if acquired:
                self.semaphore.release()
            self.tasks.pop(job_id, None)

    async def _consume(self, engine, model, messages, record, started):
        async for chunk in engine.stream(model, messages, record.parameters):
            if (
                len(record.content)
                + len(record.reasoning_content)
                + len(chunk.content)
                + len(chunk.reasoning_content)
                > 1_000_000
            ):
                raise TextError("generation_limit_exceeded", 422)
            elapsed = time.monotonic() - started
            if (chunk.content or chunk.reasoning_content) and record.ttft_seconds is None:
                record.ttft_seconds = elapsed
            if chunk.content and record.first_answer_seconds is None:
                record.first_answer_seconds = elapsed
            record.content += chunk.content
            record.reasoning_content += chunk.reasoning_content
            record.generation_seconds = elapsed
            for field in ("input_tokens", "output_tokens", "tokens_per_second", "finish_reason"):
                value = getattr(chunk, field)
                if value is not None:
                    setattr(record, field, value)
            if record.input_tokens is not None and record.output_tokens is not None:
                record.context_used_tokens = record.input_tokens + record.output_tokens
            await self._persist(record)

    async def cancel(self, job_id):
        # Simultaneous clients must not repeatedly cancel the worker during cleanup.
        async with self.cancellation_lock:
            record = self.record(job_id)
            if record.state in TERMINAL:
                return record
            task = self.tasks.get(job_id)
            if task:
                task.cancel()
                completion = asyncio.gather(task, return_exceptions=True)
                try:
                    await asyncio.shield(completion)
                except asyncio.CancelledError:
                    await completion
                    raise
            record = self.record(job_id)
            if record.state not in TERMINAL:
                record.state = "cancelled"
                await self._persist(record)
            return record

    async def close(self):
        for job_id in list(self.tasks):
            await self.cancel(job_id)
        for engine in self.engines.values():
            await engine.stop()
