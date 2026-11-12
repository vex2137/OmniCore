"""Bounded agent context within the existing user-selected model context window."""

import json
import math

from omnicore.text.types import TextError


def estimate(value):
    return math.ceil(len(json.dumps(value, ensure_ascii=False).encode()) / 4)


def bounded_result(result, limit=4096):
    result = dict(result)
    if isinstance(result.get("text"), str):
        raw = result["text"].encode()
        if len(raw) > limit:
            result.update(
                text=raw[:limit].decode("utf-8", errors="ignore"),
                truncated=True,
                original_bytes=len(raw),
            )
    if isinstance(result.get("entries"), list) and len(result["entries"]) > 40:
        result.update(entries=result["entries"][:40], truncated=True)
    return result


def messages_for_turn(base, rounds, record, parameters):
    # Keep the current task and folder IDs; discard older conversation turns first.
    base = list(base)
    checkpoint = {
        "plan": record.get("plan", []),
        "operations": [
            {
                "tool": step["tool"],
                "state": step["state"],
                "result": step.get("result_summary"),
                "error": step.get("error_code"),
            }
            for step in record["steps"]
        ],
    }
    summary = (
        [{"role": "user", "content": "Untrusted progress checkpoint: " + json.dumps(checkpoint)}]
        if record["steps"] or record.get("plan")
        else []
    )
    recent = list(rounds[-2:])
    reserve = parameters.max_tokens
    while True:
        messages = base + summary + [message for group in recent for message in group]
        used = estimate(messages)
        if used + reserve <= parameters.context_size:
            record["context"] = {
                "approx_tokens": used,
                "limit": parameters.context_size,
                "reserved_output": reserve,
                "approximate": True,
            }
            return messages
        if len(base) > 3:
            base.pop(1)
        elif len(recent) > 1:
            recent.pop(0)
        else:
            # Never silently discard the newest tool result or the current task.
            raise TextError("agent_context_limit", 422)
