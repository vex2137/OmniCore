"""Official OpenAI Chat Completions, Anthropic Messages and Gemini GenerateContent wire adapters."""

import json
from urllib.parse import quote

from omnicore.text.types import TextChunk, TextError

ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openrouter": "https://openrouter.ai/api/v1",
}


def status_error(status):
    code = {
        401: "provider_auth_failed",
        403: "provider_auth_failed",
        429: "provider_rate_limited",
        404: "provider_model_not_found",
    }.get(status, "provider_unavailable" if status >= 500 else "provider_request_rejected")
    return TextError(code, 503 if status >= 500 else 429 if status == 429 else 422)


def headers(kind, key):
    if kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if kind == "gemini":
        return {"x-goog-api-key": key}
    return {"Authorization": "Bearer " + key} if key else {}


def generation(kind, model, messages, parameters, sampling):
    wire = [{"role": m.role, "content": m.content} for m in messages]
    if kind in {"openai", "openrouter", "custom"}:
        body = {
            "model": model,
            "messages": wire,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens" if kind == "openai" else "max_tokens": parameters.max_tokens,
        }
        if sampling:
            body.update(temperature=parameters.temperature, top_p=parameters.top_p)
        return "chat/completions", None, body
    system = "\n".join(m.content for m in messages if m.role == "system")
    turns = [m for m in messages if m.role != "system"]
    if kind == "anthropic":
        body = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in turns],
            "max_tokens": parameters.max_tokens,
            "stream": True,
        }
        if system:
            body["system"] = system
        if sampling:
            if parameters.temperature > 1:
                raise TextError("provider_parameter_unsupported", 422)
            body["temperature"] = parameters.temperature
        return "messages", None, body
    if kind == "gemini":
        body = {
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in turns
            ],
            "generationConfig": {"maxOutputTokens": parameters.max_tokens},
        }
        if sampling:
            body["generationConfig"].update(
                temperature=parameters.temperature, topP=parameters.top_p
            )
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return (
            "models/" + quote(model.removeprefix("models/"), safe="") + ":streamGenerateContent",
            {"alt": "sse"},
            body,
        )
    raise TextError("unsupported_backend", 422)


async def bounded_lines(response):
    buffer = b""
    async for chunk in response.aiter_bytes():
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if len(line) > 1_048_576:
                raise TextError("provider_response_invalid", 502)
            try:
                yield line.decode("utf-8").rstrip("\r")
            except UnicodeDecodeError:
                raise TextError("provider_response_invalid", 502) from None
        if len(buffer) > 1_048_576:
            raise TextError("provider_response_invalid", 502)
    if buffer:
        try:
            yield buffer.decode("utf-8").rstrip("\r")
        except UnicodeDecodeError:
            raise TextError("provider_response_invalid", 502) from None


async def read_json(response):
    data = bytearray()
    async for chunk in response.aiter_bytes():
        if len(data) + len(chunk) > 4_194_304:
            raise TextError("provider_response_invalid", 502)
        data.extend(chunk)
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except ValueError:
        raise TextError("provider_response_invalid", 502) from None


async def events(response):
    data, size = [], 0
    async for line in bounded_lines(response):
        size += len(line)
        if size > 1_048_576:
            raise TextError("provider_response_invalid", 502)
        if not line:
            if data:
                raw = "\n".join(data)
                if raw.strip() == "[DONE]":
                    return
                try:
                    yield json.loads(raw)
                except (ValueError, TypeError):
                    raise TextError("provider_response_invalid", 502) from None
            data, size = [], 0
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        raw = "\n".join(data)
        if raw.strip() != "[DONE]":
            try:
                yield json.loads(raw)
            except ValueError:
                raise TextError("provider_response_invalid", 502) from None


def chunks(kind, event):
    if not isinstance(event, dict):
        raise TextError("provider_response_invalid", 502)
    if "error" in event or event.get("type") == "error":
        error = event.get("error") or {}
        type_ = error.get("type", "") if isinstance(error, dict) else ""
        raise TextError(
            "provider_rate_limited"
            if type_ in {"rate_limit_error", "rate_limit_exceeded"}
            else "provider_auth_failed"
            if type_ == "authentication_error"
            else "provider_request_rejected",
            502,
        )
    if kind in {"openai", "openrouter", "custom"}:
        usage = event.get("usage") or {}
        if usage:
            yield TextChunk(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            finish = choice.get("finish_reason")
            if finish in {"content_filter", "tool_calls", "function_call"}:
                raise TextError("provider_content_blocked", 422)
            yield TextChunk(
                content=delta.get("content") or "",
                reasoning_content=delta.get("reasoning_content") or "",
                finish_reason=finish if finish in {"stop", "length"} else None,
            )
    elif kind == "anthropic":
        if event.get("type") == "message_start":
            usage = event.get("message", {}).get("usage") or {}
            yield TextChunk(
                input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens")
            )
        elif event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            yield TextChunk(
                content=delta.get("text") or "", reasoning_content=delta.get("thinking") or ""
            )
        elif event.get("type") == "message_delta":
            usage = event.get("usage") or {}
            reason = (event.get("delta") or {}).get("stop_reason")
            if reason in {"refusal", "tool_use"}:
                raise TextError("provider_content_blocked", 422)
            yield TextChunk(
                output_tokens=usage.get("output_tokens"),
                finish_reason="length" if reason == "max_tokens" else "stop" if reason else None,
            )
    else:
        usage = event.get("usageMetadata") or {}
        if usage:
            yield TextChunk(
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
            )
        if (event.get("promptFeedback") or {}).get("blockReason"):
            raise TextError("provider_content_blocked", 422)
        for candidate in event.get("candidates") or []:
            reason = candidate.get("finishReason")
            if reason and reason not in {"STOP", "MAX_TOKENS"}:
                raise TextError("provider_content_blocked", 422)
            for part in (candidate.get("content") or {}).get("parts") or []:
                if isinstance(part.get("text"), str):
                    yield TextChunk(
                        **{"reasoning_content" if part.get("thought") else "content": part["text"]}
                    )
            if reason:
                yield TextChunk(finish_reason="length" if reason == "MAX_TOKENS" else "stop")
