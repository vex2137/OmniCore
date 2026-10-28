"""Additive Text AI routes. Process configuration is never accepted from API clients."""

import asyncio
import json
from pathlib import Path
from typing import Literal

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from omnicore.config import RuntimeConfig
from omnicore.diagnostics import HardwareSnapshot, hardware_snapshot
from omnicore.events import EventHub
from omnicore.schemas import BackendInfo, WireModel
from omnicore.text.conversations import (
    Conversation,
    ConversationExport,
    Conversations,
    MessageRecord,
)
from omnicore.text.downloads import DownloadManager, DownloadRecord, HuggingFace, RemoteFile
from omnicore.text.engines import LlamaEngine, OllamaEngine
from omnicore.text.files import FilePolicy
from omnicore.text.generation import (
    TERMINAL,
    GenerationManager,
    GenerationRecord,
    GenerationRequest,
)
from omnicore.text.models import ModelManager
from omnicore.text.store import ModelRecord, TextStore
from omnicore.text.types import GenerationParameters, TextError


class ModelImport(WireModel):
    path: str = Field(min_length=1, max_length=4096)


class ModelDelete(WireModel):
    delete_file: bool = False
    confirm_name: str | None = Field(default=None, max_length=256)


class ConversationCreate(WireModel):
    title: str = Field(default="", max_length=256)
    model_id: str | None = None
    parameters: GenerationParameters | None = None


class ConversationUpdate(WireModel):
    title: str | None = Field(default=None, max_length=256)
    model_id: str | None = None
    parameters: GenerationParameters | None = None

    @field_validator("title", "parameters")
    @classmethod
    def non_null_when_provided(cls, value):
        if value is None:
            raise ValueError("This field cannot be null")
        return value


class MessageCreate(WireModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str = Field(min_length=1, max_length=60000)


class DownloadCreate(WireModel):
    repository: str = Field(min_length=1, max_length=256)
    filename: str = Field(min_length=1, max_length=2048)
    revision: str = Field(default="main", max_length=128)
    confirmed: bool = False
    expected_size: int = Field(gt=0)


class GenerationWatch(WireModel):
    type: Literal["generation.watch"]
    job_id: str = Field(min_length=1, max_length=128)
    cancel_on_disconnect: bool = True


class EngineDiagnostic(WireModel):
    info: BackendInfo
    executable: str | None = None
    gpu_devices: list[str] = Field(default_factory=list)


class TaskDiagnostic(WireModel):
    id: str
    model_id: str
    state: str
    error_code: str | None = None


class TextDiagnostic(WireModel):
    hardware: HardwareSnapshot
    generations: list[TaskDiagnostic]


class TextService:
    def __init__(self, db, config: RuntimeConfig, hub: EventHub):
        self.config = config
        self.store = TextStore(db)
        directory = config.data_dir.absolute() / "models"
        self.models = ModelManager(self.store, FilePolicy((*config.model_roots, directory)))
        self.llama = LlamaEngine(
            config.llama_server,
            chat_template=config.llama_chat_template,
            request_timeout=config.generation_timeout,
        )
        self.engines = {"llama.cpp": self.llama}
        if config.ollama_enabled:
            self.engines["ollama"] = OllamaEngine(
                config.ollama_url, timeout=config.generation_timeout
            )
        self.downloads = DownloadManager(self.store, HuggingFace(config.hf_token), directory)
        self.generations = GenerationManager(
            self.store, self.models, self.engines, hub, timeout=config.generation_timeout
        )
        self.history = Conversations(self.store)

    def initialize(self):
        self.store.initialize()
        self.downloads.initialize()
        self.generations.initialize()

    async def close(self):
        await self.generations.close()
        await self.downloads.close()

    def require_idle(self, *, model_id=None, conversation_id=None):
        if self.generations.active_for(model_id=model_id, conversation_id=conversation_id):
            raise TextError("conversation_busy", 409)


def routes(service: TextService):
    router = APIRouter(prefix="/api/v1/text", tags=["Text AI"])

    @router.get("/diagnostics", response_model=TextDiagnostic)
    async def diagnostics():
        hardware = await run_in_threadpool(hardware_snapshot, service.config.data_dir)

        def records():
            return [
                TaskDiagnostic(**{k: record[k] for k in ("id", "model_id", "state", "error_code")})
                for record in service.store.jobs("generation")[:100]
            ]

        return TextDiagnostic(hardware=hardware, generations=await run_in_threadpool(records))

    @router.get("/engines", response_model=list[EngineDiagnostic])
    async def engines():
        records = []
        for engine in service.engines.values():
            info = await engine.probe()
            if info.available:
                info.resources = await engine.resources()
            records.append(
                EngineDiagnostic(
                    info=info,
                    executable=str(engine.executable)
                    if isinstance(engine, LlamaEngine) and engine.executable
                    else None,
                    gpu_devices=engine.devices if isinstance(engine, LlamaEngine) else [],
                )
            )
        return records

    @router.get("/status", response_model=dict[str, int])
    def status():
        with service.store.db.connect() as connection:
            version = connection.execute("SELECT version FROM text_schema WHERE id=1").fetchone()[0]
        return {
            "schema_version": version,
            "generation_concurrency": 1,
            "generation_queue_limit": 16,
        }

    @router.get("/models", response_model=list[ModelRecord])
    def models(
        query: str = Query(default="", max_length=256),
        backend: str = Query(default="", max_length=32),
        format: str = Query(default="", max_length=32),
    ):
        return service.store.models(query, backend, format)

    @router.post("/models/import", response_model=ModelRecord, status_code=201)
    def import_model(body: ModelImport):
        return service.models.import_gguf(Path(body.path))

    @router.post("/models/sync-ollama", response_model=list[ModelRecord])
    async def sync_ollama():
        engine = service.engines.get("ollama")
        if engine is None:
            raise TextError("engine_unavailable", 503)
        return await service.models.register_ollama(engine)

    @router.get("/models/{model_id}", response_model=ModelRecord)
    def model(model_id: str):
        return service.store.model(model_id)

    @router.put("/models/{model_id}/parameters", response_model=ModelRecord)
    def model_parameters(model_id: str, body: GenerationParameters):
        record = service.store.model(model_id)
        record.parameters = body.model_dump(mode="json")
        return service.store.update_model(record)

    @router.post("/models/{model_id}/load", response_model=ModelRecord)
    async def load(model_id: str, body: GenerationParameters):
        service.require_idle()
        async with service.generations.semaphore:
            service.require_idle()
            record = await run_in_threadpool(service.store.model, model_id)
            path = await run_in_threadpool(service.models.validated_reference, model_id)
            with service.models.policy.open(path) as stream:
                await service.llama.load(path, body, file_descriptor=stream.fileno())
            if record.compatibility != "tested":
                record.compatibility = "load_verified"
            record.parameters = body.model_dump(mode="json")
            record.capabilities = await service.llama.capabilities(str(path))
            return await run_in_threadpool(service.store.update_model, record)

    @router.post("/models/{model_id}/unload", response_model=dict[str, str])
    async def unload(model_id: str):
        service.require_idle()
        async with service.generations.semaphore:
            service.require_idle()
            record = await run_in_threadpool(service.store.model, model_id)
            engine = service.engines.get(record.backend)
            if engine:
                await engine.unload(record.location if record.backend == "ollama" else None)
            return {"status": "unloaded"}

    @router.delete("/models/{model_id}", response_model=dict[str, str])
    async def delete_model(model_id: str, body: ModelDelete):
        service.require_idle()
        async with service.generations.semaphore:
            service.require_idle()
            record = await run_in_threadpool(service.store.model, model_id)
            if service.llama.model == record.location:
                await service.llama.unload()
            await run_in_threadpool(service.models.remove, model_id, **body.model_dump())
            return {"status": "removed"}

    @router.get("/huggingface/search", response_model=list[dict[str, str | None]])
    async def hf_search(query: str = Query(min_length=1, max_length=256)):
        return await service.downloads.hub.search(query)

    @router.get("/huggingface/files", response_model=list[RemoteFile])
    async def hf_files(
        repository: str = Query(max_length=256),
        revision: str = Query(default="main", max_length=128),
    ):
        return await service.downloads.hub.files(repository, revision)

    @router.post("/downloads", response_model=DownloadRecord, status_code=202)
    async def create_download(body: DownloadCreate):
        if not body.confirmed:
            raise TextError("confirmation_required", 409)
        files = await service.downloads.hub.files(body.repository, body.revision)
        source = next((file for file in files if file.filename == body.filename), None)
        if source is None:
            raise TextError("not_found", 404)
        return await service.downloads.start(
            source, confirmed=body.confirmed, expected_size=body.expected_size
        )

    @router.get("/downloads", response_model=list[DownloadRecord])
    def downloads():
        return [
            DownloadRecord.model_validate(record) for record in service.store.jobs("download")[:100]
        ]

    @router.get("/downloads/{job_id}", response_model=DownloadRecord)
    def download(job_id: str):
        return service.downloads.record(job_id)

    @router.post("/downloads/{job_id}/cancel", response_model=DownloadRecord)
    async def cancel_download(job_id: str):
        return await service.downloads.cancel(job_id)

    @router.post("/downloads/{job_id}/resume", response_model=DownloadRecord)
    async def resume_download(job_id: str):
        return await service.downloads.resume(job_id)

    @router.post("/conversations/import", response_model=Conversation, status_code=201)
    def import_conversation(body: ConversationExport):
        return service.history.import_json(body)

    @router.post("/conversations", response_model=Conversation, status_code=201)
    def create_conversation(body: ConversationCreate):
        parameters = body.parameters
        if body.model_id:
            model = service.store.model(body.model_id)
            if parameters is None and model.parameters:
                parameters = GenerationParameters.model_validate(model.parameters)
        return service.history.create(body.title, body.model_id, parameters)

    @router.get("/conversations", response_model=list[Conversation])
    def conversations(query: str = Query(default="", max_length=256)):
        return service.history.list(query)

    @router.get("/conversations/{conversation_id}", response_model=Conversation)
    def conversation(conversation_id: str):
        return service.history.get(conversation_id)

    @router.patch("/conversations/{conversation_id}", response_model=Conversation)
    def update_conversation(conversation_id: str, body: ConversationUpdate):
        service.require_idle(conversation_id=conversation_id)
        if body.model_id:
            service.store.model(body.model_id)
        return service.history.update(conversation_id, **body.model_dump(exclude_unset=True))

    @router.delete("/conversations/{conversation_id}", response_model=dict[str, str])
    def delete_conversation(conversation_id: str):
        service.require_idle(conversation_id=conversation_id)
        service.history.delete(conversation_id)
        return {"status": "removed"}

    @router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRecord])
    def messages(conversation_id: str, query: str = Query(default="", max_length=256)):
        return service.history.messages(conversation_id, query)

    @router.post(
        "/conversations/{conversation_id}/messages", response_model=MessageRecord, status_code=201
    )
    def add_message(conversation_id: str, body: MessageCreate):
        service.require_idle(conversation_id=conversation_id)
        return service.history.add_message(conversation_id, **body.model_dump())

    @router.get("/conversations/{conversation_id}/export", response_model=ConversationExport)
    def export_conversation(conversation_id: str):
        return service.history.export(conversation_id)

    @router.post(
        "/conversations/{conversation_id}/generations",
        response_model=GenerationRecord,
        status_code=202,
    )
    async def generate(conversation_id: str, body: GenerationRequest):
        return await service.generations.submit(conversation_id, body)

    @router.get("/generations/{job_id}", response_model=GenerationRecord)
    def generation(job_id: str):
        return service.generations.record(job_id)

    @router.post("/generations/{job_id}/cancel", response_model=GenerationRecord)
    async def cancel(job_id: str):
        return await service.generations.cancel(job_id)

    @router.get(
        "/generations/{job_id}/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def stream(job_id: str, request: Request, cancel_on_disconnect: bool = True):
        service.generations.record(job_id)

        async def snapshots():
            previous = -1
            try:
                while True:
                    record = await run_in_threadpool(service.generations.record, job_id)
                    if record.sequence != previous:
                        previous = record.sequence
                        yield (
                            "data: "
                            + json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
                            + "\n\n"
                        )
                    if record.state in TERMINAL:
                        break
                    if await request.is_disconnected():
                        break
                    await asyncio.sleep(0.05)
            finally:
                if cancel_on_disconnect:
                    with anyio.CancelScope(shield=True):
                        await service.generations.cancel(job_id)

        return StreamingResponse(
            snapshots(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
