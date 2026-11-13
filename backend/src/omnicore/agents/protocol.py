"""Strict complete-message protocol. No extraction of commands from prose."""

import json
import re
from typing import Literal

from pydantic import Field

from omnicore.schemas import WireModel
from omnicore.text.types import TextError


class PlanItem(WireModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    title: str = Field(min_length=1, max_length=120)


class PlanUpdate(WireModel):
    kind: Literal["plan"]
    steps: list[PlanItem] = Field(min_length=1, max_length=32)


class ToolCall(WireModel):
    kind: Literal["tool"]
    name: str = Field(min_length=1, max_length=64)
    arguments: dict
    call_id: str | None = Field(default=None, min_length=1, max_length=128)
    step_id: str | None = Field(default=None, max_length=32)
    text: str = Field(default="", max_length=2048)


class Final(WireModel):
    kind: Literal["final"]
    text: str = Field(min_length=1, max_length=60000)


_THINK_RE = re.compile(r"^\s*(?:<think>[\s\S]*?</think>\s*)+", re.DOTALL)
_TOOL_CALL_RE = re.compile(r"^\s*<tool_call>\s*([\s\S]*?)\s*</tool_call>\s*$")
_XML_FUNC_RE = re.compile(r"^\s*<function=([a-zA-Z0-9_-]+)>\s*([\s\S]*?)\s*</function>\s*$")
_XML_PARAM_RE = re.compile(r"<parameter=([a-zA-Z0-9_-]+)>\r?\n?([\s\S]*?)\r?\n?</parameter>")
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(\{[\s\S]*\})\s*```\s*$")


def _parse_non_native(response: str) -> dict:
    if not isinstance(response, str):
        raise TextError("agent_protocol_invalid", 422)
    text = _THINK_RE.sub("", response).strip()
    tool_match = _TOOL_CALL_RE.fullmatch(text)
    if tool_match:
        inner = tool_match.group(1).strip()
        fn_match = _XML_FUNC_RE.fullmatch(inner)
        if fn_match:
            params = {}
            for key, raw_val in _XML_PARAM_RE.findall(fn_match.group(2)):
                val = re.sub(r"^\r?\n|\r?\n$", "", raw_val)
                params[key] = val
            return {"kind": "tool", "name": fn_match.group(1), "arguments": params}
        text = inner
    else:
        fence_match = _FENCE_RE.fullmatch(text)
        if fence_match:
            text = fence_match.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError:
        raise TextError("agent_protocol_invalid", 422) from None
    if not isinstance(data, dict):
        raise TextError("agent_protocol_invalid", 422)
    if "kind" not in data:
        if "name" in data and isinstance(data.get("arguments"), dict):
            data = {
                "kind": "tool",
                "name": data["name"],
                "arguments": data["arguments"],
                **{k: data[k] for k in ("call_id", "step_id", "text") if k in data},
            }
        elif "tool" in data and isinstance(data.get("arguments"), dict):
            data = {"kind": "tool", "name": data["tool"], "arguments": data["arguments"]}
        elif data and set(data.keys()) <= {"final", "answer", "text", "response"}:
            val = next((v for v in data.values() if isinstance(v, str) and v.strip()), None)
            if val is not None:
                data = {"kind": "final", "text": val}
    return data


def parse_turn(response, native):
    if native:
        if not isinstance(response, dict):
            raise TextError("agent_protocol_invalid", 422)
        calls = response.get("tool_calls")
        if calls is not None and not isinstance(calls, list):
            raise TextError("agent_protocol_invalid", 422)
        if calls:
            if len(calls) > 8:
                raise TextError("agent_protocol_invalid", 422)
            result = []
            for call in calls:
                fn = call["function"]
                args = fn["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)
                result.append(
                    ToolCall.model_validate(
                        {
                            "kind": "tool",
                            "name": fn["name"],
                            "arguments": args,
                            "call_id": call.get("id"),
                        },
                        strict=True,
                    )
                )
            return result
        return Final.model_validate({"kind": "final", "text": response.get("content")}, strict=True)
    data = _parse_non_native(response)
    if data.get("kind") == "final":
        return Final.model_validate(data, strict=True)
    if data.get("kind") == "plan":
        return PlanUpdate.model_validate(data, strict=True)
    return [ToolCall.model_validate(data, strict=True)]
