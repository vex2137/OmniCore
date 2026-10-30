"""Real engine transports. A configured executable is administrator-controlled."""

import asyncio
import json
import os
import re
import shutil
import signal
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from omnicore.config import is_loopback
from omnicore.schemas import BackendInfo, Capability, ResourceUsage
from omnicore.text import nvidia
from omnicore.text.native import engine_candidates, restricted_cpu_threads
from omnicore.text.reasoning import normalize_stream, sse_data
from omnicore.text.types import EngineModel, GenerationParameters, TextChunk, TextError, TextMessage


def engine_error(error: Exception) -> TextError:
    if isinstance(error, (ValueError, KeyError, TypeError)):
        return TextError("engine_invalid_response", 502)
    if isinstance(error, httpx.TimeoutException):
        return TextError("engine_timeout", 504)
    if isinstance(error, httpx.HTTPStatusError):
        body = error.response.text.lower()[:8192]
        if any(
            word in body for word in ["out of memory", "insufficient memory", "cudamalloc failed"]
        ):
            return TextError("out_of_memory", 503)
        if any(
            word in body
            for word in [
                "context size",
                "context window",
                "prompt is too long",
                "exceeds the available context",
            ]
        ):
            return TextError("context_limit_exceeded", 422)
        return TextError("engine_rejected_request", 502)
    return TextError("engine_unavailable", 503)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part.get("text", "")
            for part in value
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    raise TextError("engine_invalid_response", 502)


def openai_chunk(item):
    if not isinstance(item, dict):
        raise TextError("engine_invalid_response", 502)
    if item.get("error"):
        raise TextError("engine_rejected_request", 502)
    choices = item.get("choices") or []
    text, reasoning, finish = "", "", None
    # A single requested completion; never concatenate unrelated n>1 choices.
    for choice in choices:
        if choice.get("index", 0) != 0:
            continue
        delta = choice.get("delta") or choice.get("message") or {}
        text += _text(delta.get("content"))
        reasoning += _text(delta.get("reasoning_content") or delta.get("reasoning"))
        finish = choice.get("finish_reason") or finish
    usage, timing = item.get("usage") or {}, item.get("timings") or {}
    return TextChunk(
        content=text,
        reasoning_content=reasoning,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        tokens_per_second=timing.get("predicted_per_second"),
        finish_reason=finish,
    )


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

    def __init__(self, url: str = "http://127.0.0.1:11434", *, client=None, timeout=300):
        self.client = client or client_for(url, timeout=timeout)
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
            response = await self.client.post("/api/show", json={"model": model}, timeout=5)
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
            response = await self.client.get("/api/tags", timeout=5)
            response.raise_for_status()
            records = []
            for item in response.json().get("models", []):
                license = None
                capabilities = await self.capabilities(item["name"])
                try:
                    details = await self.client.post(
                        "/api/show", json={"model": item["name"]}, timeout=5
                    )
                    details.raise_for_status()
                    raw_license = details.json().get("license")
                    license = raw_license[:16384] if isinstance(raw_license, str) else None
                except (httpx.HTTPError, ValueError):
                    pass
                records.append(
                    EngineModel(
                        name=item["name"],
                        size_bytes=item.get("size", 0),
                        quantization=item.get("details", {}).get("quantization_level"),
                        license=license,
                        capabilities=capabilities,
                    )
                )
            return records
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise engine_error(exc) from None

    async def stream(self, model, messages, parameters):
        async for chunk in normalize_stream(self._stream(model, messages, parameters)):
            yield chunk

    async def _stream(self, model, messages, parameters):
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
                    "think": parameters.thinking,
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
                            content=_text(item.get("message", {}).get("content")),
                            reasoning_content=_text(item.get("message", {}).get("thinking")),
                            finish_reason=item.get("done_reason") if item.get("done") else None,
                            input_tokens=item.get("prompt_eval_count")
                            if item.get("done")
                            else None,
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
        cuda_executable: Path | None = None,
        chat_template: str | None = None,
        request_timeout: float = 300,
    ):
        found = str(executable) if executable else shutil.which("llama-server")
        self.executable = Path(found).absolute() if found else None
        self.cuda_executable = cuda_executable.absolute() if cuda_executable else None
        self._device_executables = {}
        self._cpu_executable = self.executable
        self.candidates = []
        self.offloaded_layers = None
        self.execution_device = None
        self.fallback_reason = None
        self.startup_timeout = startup_timeout
        self.chat_template = chat_template
        self.request_timeout = request_timeout
        self.process: asyncio.subprocess.Process | None = None
        self.client: httpx.AsyncClient | None = None
        self.model: str | None = None
        self.parameters: tuple | None = None
        self.version: str | None = None
        self.devices: list[str] = []
        self._lock = asyncio.Lock()
        self._generation_task: asyncio.Task | None = None
        self._log = bytearray()
        self._log_task: asyncio.Task | None = None
        self._observed_offload = 0
        self._verified_text_models: set[str] = set()

    def _guarded_command(self, *arguments, executable=None):
        bootstrap = (
            [sys.executable, "--engine-guard"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "omnicore.text.process_guard"]
        )
        return [
            *bootstrap,
            str(os.getpid()),
            str(executable or self.executable),
            *arguments,
        ]

    async def _command(self, *arguments: str, executable=None) -> str:
        executable = executable or self.executable
        if not executable or not executable.is_file() or not os.access(executable, os.X_OK):
            raise TextError("engine_unavailable", 503)
        try:
            process = await asyncio.create_subprocess_exec(
                *self._guarded_command(*arguments, executable=executable),
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
                code = (
                    "cuda_runtime_unavailable"
                    if any(
                        value in output.lower()
                        for value in (
                            b"cannot open shared object",
                            b"error while loading shared libraries",
                            b"libcuda",
                        )
                    )
                    else "engine_unavailable"
                )
                raise TextError(code, 503)
            return output.decode(errors="replace")[:65536]
        except (OSError, TimeoutError):
            raise TextError("engine_unavailable", 503) from None

    async def probe(self) -> BackendInfo:
        available = []
        devices = {}
        # CUDA and CPU remain independent binaries: missing CUDA runtime/driver must not
        # prevent the mandatory CPU engine from starting. No shell or library-path mutation.
        candidates = []
        for executable in engine_candidates(self.cuda_executable, self.executable):
            if not executable:
                continue
            try:
                version = (await self._command("--version", executable=executable)).strip()
                output = await self._command("--list-devices", executable=executable)
                available.append((executable, version))
                detected = []
                for line in output.splitlines():
                    match = re.match(r"^\s*((?:CUDA|Vulkan|SYCL|ROCm|Metal)\d+):(?:\s|$)", line)
                    if match:
                        devices.setdefault(match[1], executable)
                        detected.append(match[1])
                candidates.append(
                    {
                        "path": str(executable),
                        "available": True,
                        "devices": detected,
                        "version": version[:1024],
                        "error_code": None,
                    }
                )
            except TextError as exc:
                if executable.is_file():
                    candidates.append(
                        {
                            "path": str(executable),
                            "available": False,
                            "devices": [],
                            "version": None,
                            "error_code": exc.code,
                        }
                    )
        self.candidates = candidates
        self._device_executables, self.devices = devices, list(devices)
        self._cpu_executable = next(
            (p for p, _ in available if p == self.executable),
            available[0][0] if available else None,
        )
        self.version = available[0][1] if available else None
        return BackendInfo(
            id=self.id,
            version=self.version,
            available=bool(available),
            capabilities=[Capability.TEXT] if available else [],
            resources=await self.resources(),
        )

    async def models(self) -> list[EngineModel]:
        return (
            [EngineModel(name=self.model, capabilities=await self.capabilities(self.model))]
            if self.model
            else []
        )

    async def capabilities(self, model: str) -> list[str]:
        # Loading a model is not proof it can generate text (e.g. embedding-only architectures).
        return (
            ["text-generation"]
            if self.model == model and model in self._verified_text_models
            else []
        )

    async def load(self, path: Path, parameters: GenerationParameters, file_descriptor=None):
        async with self._lock:
            if not (await self.probe()).available:
                raise TextError("engine_unavailable", 503)
            wants_gpu = parameters.gpu_layers > 0 and parameters.device != "cpu"
            selected_device = parameters.device
            if selected_device in {"cuda", "CUDA"}:
                selected_device = next((d for d in self.devices if d.startswith("CUDA")), "CUDA0")
            if selected_device == "auto":
                selected_device = self.devices[0] if wants_gpu and self.devices else "cpu"
            if selected_device not in {"cpu", *self.devices}:
                error = next((c["error_code"] for c in self.candidates if c["error_code"]), None)
                raise TextError(error or "gpu_unavailable", 422)
            if not parameters.gpu_layers:
                if parameters.device not in {"cpu", "auto"}:
                    raise TextError("gpu_layers_required", 422)
                selected_device = "cpu"
            selected = self._device_executables.get(selected_device, self._cpu_executable)
            if not selected:
                raise TextError("engine_unavailable", 503)
            fallback = "gpu_unavailable" if wants_gpu and selected_device == "cpu" else None
            layers = parameters.gpu_layers if selected_device != "cpu" else 0
            try:
                await self._load_selected(
                    path,
                    parameters.context_size,
                    selected,
                    selected_device,
                    layers,
                    fallback,
                    file_descriptor,
                )
            except TextError as exc:
                if (
                    parameters.device != "auto"
                    or selected_device == "cpu"
                    or not self._cpu_executable
                ):
                    raise
                await self._load_selected(
                    path,
                    parameters.context_size,
                    self._cpu_executable,
                    "cpu",
                    0,
                    exc.code,
                    file_descriptor,
                )

    async def _load_selected(
        self, path, context_size, selected, selected_device, layers, fallback, file_descriptor
    ):
        threads = restricted_cpu_threads()
        desired = (str(path), context_size, layers, selected_device, str(selected), threads)
        if self.parameters == desired and self.process and self.process.returncode is None:
            self.fallback_reason = fallback
            return
        await self.unload()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        model_path = (
            f"/proc/self/fd/{file_descriptor}" if file_descriptor is not None else str(path)
        )
        arguments = [
            str(selected),
            "--model",
            model_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ctx-size",
            str(context_size),
            "--gpu-layers",
            str(layers),
            "--parallel",
            "1",
            "--no-webui",
            "-lv",
            "4",
        ]
        arguments += ["--device", "none" if selected_device == "cpu" else selected_device]
        if threads:
            arguments += [
                "--threads",
                str(threads[0]),
                "--threads-batch",
                str(threads[1]),
                "--poll",
                "0",
                "--poll-batch",
                "0",
            ]
        if self.chat_template:
            arguments += ["--chat-template", self.chat_template]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self._guarded_command(*arguments[1:], executable=selected),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=(file_descriptor,) if file_descriptor is not None else (),
            )
            self._log_task = asyncio.create_task(self._drain_log(self.process.stderr))
            self.client = client_for(f"http://127.0.0.1:{port}", timeout=self.request_timeout)
            async with asyncio.timeout(self.startup_timeout):
                while self.process.returncode is None:
                    try:
                        response = await self.client.get("/health", timeout=1)
                        if response.status_code == 200:
                            self.model = str(path)
                            self.parameters = desired
                            self.offloaded_layers = self._observed_offload
                            if selected_device != "cpu" and not self.offloaded_layers:
                                raise TextError("gpu_offload_unverified", 503)
                            self.execution_device = selected_device
                            self.fallback_reason = fallback
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
            log = bytes(self._log[-16384:]).lower()
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

    async def _drain_log(self, reader):
        # -lv 4 is required for offload evidence. Drain continuously so verbose
        # prompts cannot fill /tmp or block the engine's stderr pipe. Retain only
        # a bounded private tail; never expose raw logs through diagnostics.
        while part := await reader.read(8192):
            self._log.extend(part)
            del self._log[:-131072]
            offload = re.search(rb"offloaded (\d+)/(\d+) layers", self._log)
            if offload:
                self._observed_offload = int(offload[1])

    async def stream(self, model, messages, parameters):
        async for chunk in normalize_stream(self._stream(model, messages, parameters)):
            yield chunk

    async def _stream(self, model, messages, parameters):
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
                    "chat_template_kwargs": {"enable_thinking": parameters.thinking},
                    "reasoning_format": "deepseek",
                    **({"reasoning_effort": "none"} if not parameters.thinking else {}),
                },
            ) as response:
                if response.is_error:
                    await response.aread()
                    response.raise_for_status()
                if response.headers.get("content-type", "").startswith("application/json"):
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 2_000_000:
                            raise TextError("generation_limit_exceeded", 502)
                    chunk = openai_chunk(json.loads(body))
                    yield chunk
                    if chunk.content:
                        self._verified_text_models.add(model)
                    return
                finished = False
                seen_text = False
                async for data in sse_data(response):
                    data = data.strip()
                    if data == "[DONE]":
                        if seen_text:
                            self._verified_text_models.add(model)
                        return
                    chunk = openai_chunk(json.loads(data))
                    seen_text |= bool(chunk.content)
                    finished |= chunk.finish_reason is not None
                    yield chunk
                if not finished:
                    raise TextError("engine_stream_interrupted", 502)
                if seen_text:
                    self._verified_text_models.add(model)
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
        ram = None
        if self.process:
            with suppress(OSError, ValueError):
                for line in Path(f"/proc/{self.process.pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        ram = int(line.split()[1]) * 1024
            vram = (
                await nvidia.process_memory(self.process.pid)
                if self.execution_device and self.execution_device.startswith("CUDA")
                else None
            )
            return ResourceUsage(ram_bytes=ram, vram_bytes=vram)
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
        self.execution_device, self.offloaded_layers = None, None
        self.model, self.parameters = None, None
        self._verified_text_models.clear()
        if self._log_task:
            try:
                await asyncio.wait_for(self._log_task, 1)
            except TimeoutError:
                self._log_task.cancel()
            self._log_task = None
        self._log.clear()
        self._observed_offload = 0

    async def stop(self):
        await self.unload()
