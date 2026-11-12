"""Strict complete-message protocol. No extraction of commands from prose."""

import json
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
    data = json.loads(response)
    if not isinstance(data, dict):
        raise TextError("agent_protocol_invalid", 422)
    if data.get("kind") == "final":
        return Final.model_validate(data, strict=True)
    if data.get("kind") == "plan":
        return PlanUpdate.model_validate(data, strict=True)
    return [ToolCall.model_validate(data, strict=True)]
