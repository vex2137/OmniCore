"""Real engine transports. A configured executable is administrator-controlled."""

import asyncio
import json
import os
import shutil
import signal
import socket
import tempfile
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from omnicore.config import is_loopback
from omnicore.schemas import BackendInfo, Capability, ResourceUsage
from omnicore.text.types import EngineModel, GenerationParameters, TextChunk, TextError, TextMessage


def engine_error(error: Exception) -> TextError:
    if isinstance(error, httpx.TimeoutException):
        return TextError("engine_timeout", 504)
    if isinstance(error, httpx.HTTPStatusError):
        body = error.response.text.lower()[:8192]
        if any(word in body for word in ["out of memory", "insufficient memory", "cuda error"]):
            return TextError("out_of_memory", 503)
        return TextError("engine_rejected_request", 502)
    return TextError("engine_unavailable", 503)


def client_for(url: str, timeout: float = 30) -> httpx.AsyncClient:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Engine URL must be an HTTP(S) address without credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Engine URL must not contain a query or fragment")
    return httpx.AsyncClient(
        base_url=url.rstrip("/"),
        timeout=httpx.Timeout(timeout, connect=3),
        trust_env=not is_loopback(parsed.hostname),
        follow_redirects=False,
    )


class TextEngine(Protocol):
    id: str

    async def probe(self) -> BackendInfo: ...
    async def models(self) -> list[EngineModel]: ...
    async def capabilities(self, model: str) -> list[str]: ...
    def stream(
        self, model: str, messages: list[TextMessage], parameters: GenerationParameters
    ) -> AsyncIterator[TextChunk]: ...
    async def unload(self, model: str | None = None) -> None: ...
    async def stop(self) -> None: ...
    async def resources(self) -> ResourceUsage: ...


class OllamaEngine:
    id = "ollama"

    def __init__(self, url: str = "http://127.0.0.1:11434", *, client=None):
        self.client = client or client_for(url)
        self._streams: set[httpx.Response] = set()

    async def probe(self) -> BackendInfo:
        try:
            response = await self.client.get("/api/version", timeout=2)
            response.raise_for_status()
            return BackendInfo(
                id=self.id,
                version=str(response.json()["version"]),
                available=True,
                capabilities=[Capability.TEXT],
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return BackendInfo(id=self.id, available=False)

    async def capabilities(self, model: str) -> list[str]:
        try:
            response = await self.client.post("/api/show", json={"model": model})
            response.raise_for_status()
            known = {
                "completion": "text-generation",
                "vision": "vision-input",
                "embedding": "embeddings",
                "tools": "tool-calling",
            }
            return [
                known[item] for item in response.json().get("capabilities", []) if item in known
            ]
        except (httpx.HTTPError, ValueError):
            return []

    async def models(self) -> list[EngineModel]:
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            return [
                EngineModel(
                    name=item["name"],
                    size_bytes=item.get("size", 0),
                    quantization=item.get("details", {}).get("quantization_level"),
                )
                for item in response.json().get("models", [])
            ]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise engine_error(exc) from None

    async def stream(self, model, messages, parameters):
        if parameters.gpu_layers or parameters.device != "cpu":
            raise TextError("unsupported_parameter", 422)
        options = {
            "temperature": parameters.temperature,
            "top_p": parameters.top_p,
            "top_k": parameters.top_k,
            "repeat_penalty": parameters.repeat_penalty,
            "num_predict": parameters.max_tokens,
            "num_ctx": parameters.context_size,
            "seed": parameters.seed,
        }
        try:
            async with self.client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": model,
                    "messages": [item.model_dump() for item in messages],
                    "stream": True,
                    "options": options,
                },
            ) as response:
                if response.is_error:
                    await response.aread()
                    response.raise_for_status()
                self._streams.add(response)
                try:
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        item = json.loads(line)
                        if item.get("error"):
                            code = (
                                "out_of_memory"
                                if "memory" in str(item["error"]).lower()
                                else "engine_rejected_request"
                            )
                            raise TextError(code, 502)
                        count, duration = item.get("eval_count"), item.get("eval_duration")
                        yield TextChunk(
                            content=item.get("message", {}).get("content", ""),
                            output_tokens=count if item.get("done") else None,
                            tokens_per_second=count / (duration / 1e9)
                            if count and duration
                            else None,
                        )
                        if item.get("done"):
                            return
                    raise TextError("engine_stream_interrupted", 502)
                finally:
                    self._streams.discard(response)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise engine_error(exc) from None

    async def cancel(self) -> None:
        for response in list(self._streams):
            await response.aclose()

    async def unload(self, model=None) -> None:
        if model:
            try:
                response = await self.client.post(
                    "/api/generate",
                    json={
                        "model": model,
                        "keep_alive": 0,
                        "stream": False,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise engine_error(exc) from None

    async def resources(self) -> ResourceUsage:
        try:
            response = await self.client.get("/api/ps", timeout=2)
            response.raise_for_status()
            values = [
                item["size_vram"]
                for item in response.json().get("models", [])
                if isinstance(item.get("size_vram"), int)
            ]
            return ResourceUsage(vram_bytes=sum(values) if values else None)
        except (httpx.HTTPError, ValueError):
            return ResourceUsage()

    async def stop(self):
        await self.cancel()
        await self.client.aclose()


class LlamaEngine:
    id = "llama.cpp"

    def __init__(
        self,
        executable: Path | None = None,
        *,
        startup_timeout: float = 120,
        chat_template: str | None = None,
    ):
        found = str(executable) if executable else shutil.which("llama-server")
        self.executable = Path(found).absolute() if found else None
        self.startup_timeout = startup_timeout
        self.chat_template = chat_template
        self.process: asyncio.subprocess.Process | None = None
        self.client: httpx.AsyncClient | None = None
        self.model: str | None = None
        self.parameters: tuple | None = None
        self.version: str | None = None
        self.devices: list[str] = []
        self._lock = asyncio.Lock()
        self._generation_task: asyncio.Task | None = None
        self._log = None

    async def _command(self, *arguments: str) -> str:
        if (
            not self.executable
            or not self.executable.is_file()
            or not os.access(self.executable, os.X_OK)
        ):
            raise TextError("engine_unavailable", 503)
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.executable),
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), 10)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if process.returncode:
                raise TextError("engine_unavailable", 503)
            return output.decode(errors="replace")[:65536]
        except (OSError, TimeoutError):
            raise TextError("engine_unavailable", 503) from None

    async def probe(self) -> BackendInfo:
        try:
            self.version = (await self._command("--version")).strip()
            output = await self._command("--list-devices")
            self.devices = [
                line.strip().split(": ")[0]
                for line in output.splitlines()
                if any(marker in line for marker in ["CUDA", "Vulkan", "SYCL", "ROCm", "Metal"])
            ]
            return BackendInfo(
                id=self.id,
                version=self.version,
                available=True,
                capabilities=[Capability.TEXT],
                resources=await self.resources(),
            )
        except TextError:
            return BackendInfo(id=self.id, available=False)

    async def models(self) -> list[EngineModel]:
        return (
            [EngineModel(name=self.model, capabilities=["text-generation"])] if self.model else []
        )

    async def capabilities(self, model: str) -> list[str]:
        # Only the successfully loaded model is advertised. Vision is not inferred from GGUF alone.
        return ["text-generation"] if self.model == model else []

    async def load(self, path: Path, parameters: GenerationParameters) -> None:
        async with self._lock:
            desired = (str(path), parameters.context_size, parameters.gpu_layers, parameters.device)
            if self.parameters == desired and self.process and self.process.returncode is None:
                return
            if not (await self.probe()).available:
                raise TextError("engine_unavailable", 503)
            if (
                parameters.gpu_layers or parameters.device not in {"cpu", "auto"}
            ) and not self.devices:
                raise TextError("gpu_unavailable", 422)
            if parameters.device not in {"cpu", "auto", *self.devices}:
                raise TextError("gpu_unavailable", 422)
            await self.unload()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            arguments = [
                str(self.executable),
                "--model",
                str(path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ctx-size",
                str(parameters.context_size),
                "--gpu-layers",
                str(parameters.gpu_layers),
                "--parallel",
                "1",
                "--no-webui",
            ]
            if parameters.device == "cpu":
                arguments += ["--device", "none"]
            elif parameters.device != "auto":
                arguments += ["--device", parameters.device]
            if self.chat_template:
                arguments += ["--chat-template", self.chat_template]
            try:
                self._log = tempfile.TemporaryFile()
                self.process = await asyncio.create_subprocess_exec(
                    *arguments,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=self._log,
                    start_new_session=True,
                )
                self.client = client_for(f"http://127.0.0.1:{port}")
                async with asyncio.timeout(self.startup_timeout):
                    while self.process.returncode is None:
                        try:
                            response = await self.client.get("/health", timeout=1)
                            if response.status_code == 200:
                                self.model = str(path)
                                self.parameters = desired
                                return
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.1)
                self._log.seek(0, 2)
                size = self._log.tell()
                self._log.seek(max(0, size - 16384))
                log = self._log.read().lower()
                code = (
                    "out_of_memory"
                    if b"out of memory" in log or b"insufficient memory" in log
                    else "model_load_failed"
                )
                raise TextError(code, 502)
            except (OSError, TimeoutError):
                await self.unload()
                raise TextError("model_load_failed", 502) from None
            except BaseException:
                await self.unload()
                raise

    async def stream(self, model, messages, parameters):
        if not self.client or self.model != model:
            raise TextError("model_not_loaded", 409)
        self._generation_task = asyncio.current_task()
        try:
            async with self.client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "messages": [item.model_dump() for item in messages],
                    "stream": True,
                    "temperature": parameters.temperature,
                    "top_p": parameters.top_p,
                    "top_k": parameters.top_k,
                    "repeat_penalty": parameters.repeat_penalty,
                    "max_tokens": parameters.max_tokens,
                    "seed": parameters.seed,
                    "stream_options": {"include_usage": True},
                },
            ) as response:
                if response.is_error:
                    await response.aread()
                    response.raise_for_status()
                finished = False
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    item = json.loads(data)
                    if item.get("error"):
                        raise TextError("engine_rejected_request", 502)
                    choices = item.get("choices", [])
                    text = "".join(
                        choice.get("delta", {}).get("content") or "" for choice in choices
                    )
                    finished |= any(choice.get("finish_reason") for choice in choices)
                    yield TextChunk(
                        content=text,
                        output_tokens=item.get("usage", {}).get("completion_tokens"),
                        tokens_per_second=item.get("timings", {}).get("predicted_per_second"),
                    )
                if not finished:
                    raise TextError("engine_stream_interrupted", 502)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise engine_error(exc) from None
        finally:
            self._generation_task = None

    async def cancel(self) -> None:
        task = self._generation_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def resources(self) -> ResourceUsage:
        if self.process:
            with suppress(OSError, ValueError):
                for line in Path(f"/proc/{self.process.pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        return ResourceUsage(ram_bytes=int(line.split()[1]) * 1024)
        return ResourceUsage()

    async def unload(self, model=None) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None
        process, self.process = self.process, None
        if process and process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        self.model, self.parameters = None, None
        if self._log:
            self._log.close()
            self._log = None

    async def stop(self):
        await self.unload()
