"""Versioned wire models; runtime secrets never belong to these contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Locale(StrEnum):
    EN = "en-US"
    PL = "pl-PL"


class Theme(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class InterfaceMode(StrEnum):
    SIMPLE = "simple"
    ADVANCED = "advanced"


class Preferences(WireModel):
    schema_version: Literal[1] = 1
    locale: Locale = Locale.EN
    theme: Theme = Theme.SYSTEM
    mode: InterfaceMode = InterfaceMode.SIMPLE


class ModelMetadata(WireModel):
    """Descriptive metadata only; compatibility requires a real integration test."""

    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=256)
    format: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(ge=0)
    quantization: str | None = Field(default=None, max_length=64)
    license: str | None = Field(default=None, max_length=256)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    tested_backends: list[str] = Field(default_factory=list, max_length=32)


class Capability(StrEnum):
    TEXT = "text"
    VISION = "vision"
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    INPAINT = "inpaint"
    UPSCALE = "upscale"
    LORA = "lora"


class ResourceUsage(WireModel):
    ram_bytes: int | None = Field(default=None, ge=0)
    vram_bytes: int | None = Field(default=None, ge=0)


class BackendInfo(WireModel):
    id: str
    version: str | None = None
    available: bool
    capabilities: list[Capability] = Field(default_factory=list)
    resources: ResourceUsage = Field(default_factory=ResourceUsage)


class Health(WireModel):
    status: Literal["ok"] = "ok"
    version: str
    database_version: int


class ErrorDetail(WireModel):
    code: str
    message: str


class ErrorResponse(WireModel):
    error: ErrorDetail


class ServerEvent(WireModel):
    schema_version: Literal[1] = 1
    type: Literal["hello", "settings.updated", "pong", "error"]
    settings: Preferences | None = None
    error: ErrorDetail | None = None


class ClientEvent(WireModel):
    type: Literal["ping"]


class LocaleCatalog(WireModel):
    locale: Locale
    messages: dict[str, str]
