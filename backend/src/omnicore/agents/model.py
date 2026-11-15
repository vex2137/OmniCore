"""Existing engines, complete-response tool parsing; ordinary chat is untouched."""

import asyncio
import json
import os
import time
from contextvars import ContextVar

from omnicore.agents.capabilities import capability, native_declared
from omnicore.agents.protocol import PlanUpdate
from omnicore.agents.tools import schemas
from omnicore.text.types import TextError, TextMessage


class AgentModel:
    def __init__(self, service):
        self.service = service
        self.output_tokens = ContextVar("agent_output_tokens", default=0)
        self.backend_version = ContextVar("agent_backend_version", default=None)
        self.turn_metrics = ContextVar("agent_turn_metrics", default=None)

    async def turn(self, model, messages, parameters, protocol, tools=None):
        service = self.service
        async with service.generations.semaphore:
            engine = service.engines.get(model.backend)
            if engine is None:
                raise TextError("engine_unavailable", 503)
            proc = getattr(engine, "process", None)
            if proc is not None and proc.returncode is None and getattr(engine, "version", None):
                version = engine.version
            else:
                info = await engine.probe()
                if info is None or not info.available:
                    raise TextError("engine_unavailable", 503)
                version = info.version
            self.output_tokens.set(0)
            self.backend_version.set(version)
            location = model.location
            load_seconds = None
            if model.backend == "llama.cpp":
                path = service.models.validated_reference(model.id)
                model = service.store.model(model.id)
                with service.models.policy.open(path, registered=True) as file:
                    info = os.fstat(file.fileno())
                    if (
                        (info.st_dev, info.st_ino) != service.store.model_identity(model.id)
                        or info.st_size != model.size_bytes
                        or (
                            model.metadata.get("file_mtime_ns") is not None
                            and info.st_mtime_ns != model.metadata["file_mtime_ns"]
                        )
                    ):
                        raise TextError("model_file_changed", 409)
                    loading = time.monotonic()
                    try:
                        await engine.load(path, parameters, file_descriptor=file.fileno())
                    finally:
                        load_seconds = round(time.monotonic() - loading, 3)
                location = str(path)
            native = (
                protocol == "auto"
                and native_declared(model, engine)
                and capability(service, model)["status"] != "json"
            )
            if native:
                return await self.ollama(engine, location, messages, parameters, tools)
            # File/tool results are data in user messages, never system instructions.
            converted = [
                TextMessage(role=m["role"] if m["role"] != "tool" else "user", content=m["content"])
                for m in messages
            ]
            content, finish = "", None
            started = time.monotonic()
            first_token_at = None
            reported_input = None
            reported_output = None
            reported_prompt_sec = None
            reported_prompt_tps = None
            async with asyncio.timeout(service.config.generation_timeout):
                async for chunk in engine.stream(location, converted, parameters):
                    if (chunk.content or chunk.reasoning_content) and first_token_at is None:
                        first_token_at = time.monotonic() - started
                    content += chunk.content
                    finish = chunk.finish_reason or finish
                    if isinstance(chunk.input_tokens, int):
                        reported_input = max(reported_input or 0, chunk.input_tokens)
                    if isinstance(chunk.output_tokens, int):
                        reported_output = max(reported_output or 0, chunk.output_tokens)
                        self.output_tokens.set(reported_output)
                    if chunk.prompt_processing_seconds is not None:
                        reported_prompt_sec = chunk.prompt_processing_seconds
                    if chunk.prompt_tokens_per_second is not None:
                        reported_prompt_tps = chunk.prompt_tokens_per_second
                    if len(content.encode("utf-8")) > 65536:
                        raise TextError("agent_response_limit", 422)
            if finish != "stop":
                raise TextError("agent_incomplete_response", 422)
            gen_seconds = max(0.001, time.monotonic() - started)
            tps = (
                round(reported_output / gen_seconds, 2)
                if isinstance(reported_output, int) and reported_output > 0
                else None
            )
            used_ctx = (
                reported_input + reported_output
                if isinstance(reported_input, int) and isinstance(reported_output, int)
                else None
            )
            self.turn_metrics.set(
                {
                    "input_tokens": reported_input,
                    "output_tokens": reported_output,
                    "ttft_seconds": round(first_token_at, 3)
                    if first_token_at is not None
                    else None,
                    "prompt_processing_seconds": reported_prompt_sec,
                    "prompt_tokens_per_second": reported_prompt_tps,
                    "generation_seconds": round(gen_seconds, 3),
                    "model_load_seconds": load_seconds,
                    "tokens_per_second": tps,
                    "context_limit_tokens": parameters.context_size,
                    "context_used_tokens": used_ctx,
                    "execution_device": getattr(engine, "execution_device", None)
                    if model.backend == "llama.cpp"
                    else "cpu",
                    "gpu_offloaded_layers": getattr(engine, "offloaded_layers", None)
                    if model.backend == "llama.cpp"
                    else None,
                    "gpu_total_layers": getattr(engine, "total_layers", None)
                    if model.backend == "llama.cpp"
                    else None,
                    "gpu_offload_mode": (
                        getattr(engine, "offload_mode", None)
                        or getattr(parameters, "gpu_offload_mode", None)
                    )
                    if model.backend == "llama.cpp"
                    else "cpu",
                    "gpu_offload_reason": getattr(engine, "offload_reason", None)
                    if model.backend == "llama.cpp"
                    else None,
                    "fallback_reason": getattr(engine, "fallback_reason", None)
                    if model.backend == "llama.cpp"
                    else None,
                    "model_name": model.name,
                }
            )
            return content, False

    async def ollama(self, engine, model, messages, parameters, tools=None):
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
        # Non-streaming response is still read incrementally with a byte bound.
        async with engine.client.stream(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "think": parameters.thinking,
                "tools": [
                    *(schemas() if tools is None else tools),
                    {
                        "type": "function",
                        "function": {
                            "name": "set_plan",
                            "description": "Set or correct the bounded task plan, not file access.",
                            "parameters": PlanUpdate.model_json_schema(),
                        },
                    },
                ],
                "options": options,
            },
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for block in response.aiter_bytes():
                body.extend(block)
                if len(body) > 131072:
                    raise TextError("agent_response_limit", 422)
        result = json.loads(body)
        if not result.get("done") or result.get("done_reason") == "length":
            raise TextError("agent_incomplete_response", 422)
        count = result.get("eval_count")
        prompt_count = result.get("prompt_eval_count")
        if type(count) is int and count >= 0:
            self.output_tokens.set(count)
        self.turn_metrics.set(
            {
                "input_tokens": prompt_count if type(prompt_count) is int else None,
                "output_tokens": count if type(count) is int else None,
                "context_limit_tokens": parameters.context_size,
                "execution_device": "cpu",
                "gpu_offloaded_layers": None,
                "gpu_total_layers": None,
                "model_name": model,
            }
        )
        return result["message"], True
