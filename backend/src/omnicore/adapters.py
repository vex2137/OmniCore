"""Contracts only. Production engines are implemented and tested in later stages."""

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from omnicore.schemas import BackendInfo, Capability, ResourceUsage, WireModel


class TaskRequest(WireModel):
    id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    capability: Capability
    parameters: dict[str, object] = Field(default_factory=dict)


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskProgress(WireModel):
    task_id: str
    state: TaskState
    fraction: float | None = Field(default=None, ge=0, le=1)
    error_code: str | None = None


class EngineAdapter(Protocol):
    id: str

    async def probe(self) -> BackendInfo: ...
    async def start(self, request: TaskRequest) -> str: ...
    def events(self, task_id: str) -> AsyncIterator[TaskProgress]: ...
    async def cancel(self, task_id: str) -> None: ...
    async def stop(self) -> None: ...
    async def resources(self) -> ResourceUsage: ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, EngineAdapter] = {}

    def register(self, adapter: EngineAdapter) -> None:
        if adapter.id in self._adapters:
            raise ValueError(f"Duplicate backend ID: {adapter.id}")
        self._adapters[adapter.id] = adapter

    async def discover(self) -> list[BackendInfo]:
        return [await adapter.probe() for adapter in self._adapters.values()]
