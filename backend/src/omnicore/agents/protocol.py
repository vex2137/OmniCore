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


_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)
_TOOL_CALL_RE = re.compile(
    r"^\s*(?:(?P<prefix>[\s\S]*?)\s*)?<tool_call>\s*(?P<inner>[\s\S]*?)\s*</tool_call>\s*$"
)
_XML_FUNC_RE = re.compile(r"^\s*<function=([a-zA-Z0-9_-]+)>\s*([\s\S]*?)\s*</function>\s*$")
_XML_PARAM_RE = re.compile(r"<parameter=([a-zA-Z0-9_-]+)>\r?\n?([\s\S]*?)\r?\n?</parameter>")
_FENCE_RE = re.compile(
    r"^\s*(?:(?P<prefix>[^{}`<>]*?)\s*)?```(?:json)?\s*(?P<body>\{[\s\S]*?\})\s*```\s*$"
)
_EMBEDDED_PROTO_RE = re.compile(r'\{\s*"(?:kind|name|tool|arguments|tool_calls|steps|final)"\s*:')
_TRAILING_FINAL_JSON_RE = re.compile(
    r'(?:```(?:json)?\s*)?(\{\s*"kind"\s*:\s*"final"\s*,\s*"(?:text|answer|response|content)"\s*:\s*"[\s\S]*\})\s*(?:```\s*)?$'
)
_INVALID_JSON_ESCAPE_RE = re.compile(r"\\(?![/\"\\bfnrt]|u[0-9a-fA-F]{4})")
_UNSAFE_PROSE_CMD_RE = re.compile(r"(?i)(?:^|:\s*|\b)(?:delete|remove|unlink)\s+file\b")
_FINAL_TOOL_NAMES = {"final_answer", "final", "answer", "respond"}
_KNOWN_TOOL_NAMES = {
    "read_text",
    "write_text",
    "list_files",
    "find_files",
    "search_text",
    "file_info",
    "calculate",
    "web_search",
    "web_fetch",
    *_FINAL_TOOL_NAMES,
}
_INT_PARAM_NAMES = {"max_results"}


def _extract_final_text(mapping: dict) -> str | None:
    for key in ("text", "answer", "response", "content", "final"):
        val = mapping.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _try_parse_final_json(raw: str) -> dict | None:
    variants = [raw, _INVALID_JSON_ESCAPE_RE.sub(r"\\\\", raw)]
    if not raw.endswith("}"):
        variants.extend([raw + "}", _INVALID_JSON_ESCAPE_RE.sub(r"\\\\", raw) + "}"])
    for item in variants:
        try:
            cand = json.loads(item)
        except ValueError:
            continue
        if (
            isinstance(cand, dict)
            and cand.get("kind") == "final"
            and set(cand.keys()) <= {"kind", "text", "answer", "response", "content", "final"}
            and _extract_final_text(cand) is not None
        ):
            return {"kind": "final", "text": _extract_final_text(cand)}
    return None


def _looks_like_broken_protocol(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in {"invalid", "not json", "malformed", "syntax error"}:
        return True
    if any(
        marker in text
        for marker in (
            "<tool_call",
            "</tool_call",
            "<function=",
            "</function>",
            "<parameter=",
            "</parameter>",
        )
    ):
        return True
    if text.count("```") % 2 == 1:
        return True
    if _EMBEDDED_PROTO_RE.search(text):
        return True
    if _UNSAFE_PROSE_CMD_RE.search(text):
        return True
    return False


def is_incomplete_protocol_output(response: str, finish_reason: str | None = None) -> bool:
    if finish_reason in {"length", "max_tokens"}:
        return True
    if not isinstance(response, str):
        return False
    stripped = response.strip()
    if "<think>" in stripped and "</think>" not in stripped:
        return True
    cleaned = _THINK_BLOCK_RE.sub("", stripped).strip()
    if "<tool_call>" in cleaned and "</tool_call>" not in cleaned:
        return True
    if cleaned.startswith("{") and not cleaned.endswith("}"):
        return True
    if cleaned.startswith("```") and not cleaned.endswith("```"):
        return True
    return False


def _parse_non_native(response: str) -> dict:
    if not isinstance(response, str):
        raise TextError("agent_protocol_invalid", 422)
    text = _THINK_BLOCK_RE.sub("", response).strip()
    if not text or "<think>" in text or "</think>" in text:
        raise TextError("agent_protocol_invalid", 422)
    tool_match = _TOOL_CALL_RE.fullmatch(text)
    if tool_match:
        prefix = (tool_match.group("prefix") or "").strip()
        if prefix and any(
            tag in prefix for tag in ("<tool_call", "</tool_call", "<function=", "</function>")
        ):
            raise TextError("agent_protocol_invalid", 422)
        inner = tool_match.group("inner").strip()
        fn_match = _XML_FUNC_RE.fullmatch(inner)
        if fn_match:
            fn_name = fn_match.group(1)
            params: dict = {}
            for key, raw_val in _XML_PARAM_RE.findall(fn_match.group(2)):
                val = re.sub(r"^\r?\n|\r?\n$", "", raw_val)
                if key in _INT_PARAM_NAMES and val.strip().isdigit():
                    params[key] = int(val.strip())
                else:
                    params[key] = val
            if fn_name in _FINAL_TOOL_NAMES:
                final_text = _extract_final_text(params)
                if final_text is not None:
                    return {"kind": "final", "text": final_text}
            return {"kind": "tool", "name": fn_name, "arguments": params}
        text = inner
    else:
        fence_match = _FENCE_RE.fullmatch(text)
        if fence_match:
            prefix = (fence_match.group("prefix") or "").strip()
            if prefix and _looks_like_broken_protocol(prefix):
                raise TextError("agent_protocol_invalid", 422)
            text = fence_match.group("body").strip()
        elif not text.startswith("{") and not text.startswith("["):
            trailing_final = _TRAILING_FINAL_JSON_RE.search(text)
            if trailing_final:
                parsed_final = _try_parse_final_json(trailing_final.group(1).strip())
                if parsed_final is not None:
                    return parsed_final
            if _looks_like_broken_protocol(text):
                raise TextError("agent_protocol_invalid", 422)
            return {"kind": "final", "text": text}
    try:
        data = json.loads(text)
    except ValueError:
        recovered = _try_parse_final_json(text) if text.startswith("{") else None
        if recovered is None:
            raise TextError("agent_protocol_invalid", 422) from None
        data = recovered
    if not isinstance(data, dict):
        raise TextError("agent_protocol_invalid", 422)
    if "arguments" not in data:
        for arg_alias in ("parameters", "params", "args"):
            if isinstance(data.get(arg_alias), dict):
                data = {
                    **{k: v for k, v in data.items() if k != arg_alias},
                    "arguments": data[arg_alias],
                }
                break
    if "kind" not in data and isinstance(data.get("tool"), dict):
        t_obj = data["tool"]
        fn_obj = t_obj.get("function") if isinstance(t_obj.get("function"), dict) else t_obj
        if isinstance(fn_obj, dict) and isinstance(fn_obj.get("name"), str):
            fn_args = fn_obj.get("arguments") or fn_obj.get("parameters")
            if isinstance(fn_args, dict):
                data = {"kind": "tool", "name": fn_obj["name"], "arguments": fn_args}
    if (
        "kind" not in data
        and isinstance(data.get("tool_calls"), list)
        and len(data["tool_calls"]) == 1
        and isinstance(data["tool_calls"][0], dict)
    ):
        tc = data["tool_calls"][0]
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
        if isinstance(fn.get("name"), str) and isinstance(fn.get("arguments"), dict):
            data = {"kind": "tool", "name": fn["name"], "arguments": fn["arguments"]}
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
        elif (
            isinstance(data.get("name"), str)
            and data["name"] in _KNOWN_TOOL_NAMES
            and "arguments" not in data
        ):
            args = {
                k: v for k, v in data.items() if k not in {"name", "call_id", "step_id", "text"}
            }
            data = {
                "kind": "tool",
                "name": data["name"],
                "arguments": args,
                **{k: data[k] for k in ("call_id", "step_id", "text") if k in data},
            }
        elif (
            isinstance(data.get("tool"), str)
            and data["tool"] in _KNOWN_TOOL_NAMES
            and "arguments" not in data
        ):
            args = {
                k: v for k, v in data.items() if k not in {"tool", "call_id", "step_id", "text"}
            }
            data = {"kind": "tool", "name": data["tool"], "arguments": args}
        elif data and set(data.keys()) <= {"final", "answer", "text", "response", "content"}:
            val = _extract_final_text(data)
            if val is not None:
                data = {"kind": "final", "text": val}
    elif data.get("kind") == "final" and "text" not in data:
        val = _extract_final_text(data)
        if val is not None:
            data = {"kind": "final", "text": val}
    elif (
        data.get("kind") == "tool"
        and isinstance(data.get("name"), str)
        and data["name"] in _KNOWN_TOOL_NAMES
        and "arguments" not in data
    ):
        args = {
            k: v for k, v in data.items() if k not in {"kind", "name", "call_id", "step_id", "text"}
        }
        data = {
            "kind": "tool",
            "name": data["name"],
            "arguments": args,
            **{k: data[k] for k in ("call_id", "step_id", "text") if k in data},
        }
    elif (
        data.get("kind") not in {"tool", "final", "plan"}
        and "name" not in data
        and isinstance(data.get("kind"), str)
        and isinstance(data.get("arguments"), dict)
    ):
        data = {
            "kind": "tool",
            "name": data["kind"],
            "arguments": data["arguments"],
            **{k: data[k] for k in ("call_id", "step_id", "text") if k in data},
        }
    if (
        data.get("kind") == "tool"
        and "name" not in data
        and isinstance(data.get("arguments"), dict)
    ):
        args_dict = data["arguments"]
        if "query" in args_dict and ("grant_id" in args_dict or "path" in args_dict):
            data = {**data, "name": "search_text"}
        elif "mode" in args_dict and "content" in args_dict:
            data = {**data, "name": "write_text"}
        elif (
            isinstance(args_dict.get("path"), str)
            and args_dict["path"].strip() not in {"", "."}
            and set(args_dict.keys()) <= {"grant_id", "path"}
        ):
            data = {**data, "name": "read_text"}
        elif "grant_id" in args_dict and set(args_dict.keys()) <= {"grant_id", "path"}:
            data = {**data, "name": "list_files"}
    if (
        data.get("kind") == "tool"
        and data.get("name") in _FINAL_TOOL_NAMES
        and isinstance(data.get("arguments"), dict)
    ):
        final_text = _extract_final_text(data["arguments"])
        if final_text is not None:
            return {"kind": "final", "text": final_text}
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
