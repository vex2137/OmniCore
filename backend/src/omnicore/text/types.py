from typing import Literal

from pydantic import Field

from omnicore.schemas import WireModel


class TextError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)


class GenerationParameters(WireModel):
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    top_k: int = Field(default=40, ge=0, le=1000)
    repeat_penalty: float = Field(default=1.1, gt=0, le=3)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    context_size: int = Field(default=2048, ge=128, le=131072)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    system_prompt: str = Field(default="", max_length=16384)
    gpu_layers: int = Field(default=0, ge=0, le=999)
    device: str = Field(default="cpu", pattern=r"^(cpu|auto|[A-Za-z0-9][A-Za-z0-9_.:-]{0,63})$")


class TextMessage(WireModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=1_000_000)


class TextChunk(WireModel):
    content: str = ""
    output_tokens: int | None = Field(default=None, ge=0)
    tokens_per_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class EngineModel(WireModel):
    name: str
    size_bytes: int = 0
    quantization: str | None = None
    license: str | None = None
    capabilities: list[str] = Field(default_factory=list)
