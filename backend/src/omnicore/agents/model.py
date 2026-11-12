"""Existing engines, complete-response tool parsing; ordinary chat is untouched."""

import asyncio
import json
import os
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

    async def turn(self, model, messages, parameters, protocol):
        service = self.service
        async with service.generations.semaphore:
            engine = service.engines.get(model.backend)
            info = await engine.probe() if engine else None
            if info is None or not info.available:
                raise TextError("engine_unavailable", 503)
            self.output_tokens.set(0)
            self.backend_version.set(info.version)
            location = model.location
            if model.backend == "llama.cpp":
                path = service.models.validated_reference(model.id)
                with service.models.policy.open(path) as file:
                    info = os.fstat(file.fileno())
                    if (info.st_dev, info.st_ino) != service.store.model_identity(model.id):
                        raise TextError("model_file_changed", 409)
                    await engine.load(path, parameters, file_descriptor=file.fileno())
                location = str(path)
            native = (
                protocol == "auto"
                and native_declared(model, engine)
                and capability(service, model)["status"] != "json"
            )
            if native:
                return await self.ollama(engine, location, messages, parameters)
            # File/tool results are data in user messages, never system instructions.
            converted = [
                TextMessage(role=m["role"] if m["role"] != "tool" else "user", content=m["content"])
                for m in messages
            ]
            content, finish = "", None
            async with asyncio.timeout(service.config.generation_timeout):
                async for chunk in engine.stream(location, converted, parameters):
                    content += chunk.content
                    finish = chunk.finish_reason or finish
                    if isinstance(chunk.output_tokens, int):
                        self.output_tokens.set(max(self.output_tokens.get(), chunk.output_tokens))
                    if len(content.encode("utf-8")) > 65536:
                        raise TextError("agent_response_limit", 422)
            if finish != "stop":
                raise TextError("agent_incomplete_response", 422)
            return content, False

    async def ollama(self, engine, model, messages, parameters):
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
                    *schemas(),
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
        if type(count) is int and count >= 0:
            self.output_tokens.set(count)
        return result["message"], True
