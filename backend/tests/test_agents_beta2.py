"""Beta 2 protocol/plan/retry regressions; all models are controlled transports."""

import asyncio
import json
import struct

import httpx
import pytest
from test_agents import FINAL, finish, setup, tool, waiting
from test_text_models import synthetic_gguf

from omnicore.agents.capabilities import cache_key, capability
from omnicore.agents.context import bounded_result, messages_for_turn
from omnicore.agents.protocol import PlanUpdate, parse_turn
from omnicore.agents.service import AgentRequest, Agents
from omnicore.text.engines import OllamaEngine
from omnicore.text.types import GenerationParameters, TextError


def test_json_compatibility_persistence_and_template_invalidation(tmp_path):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [tool("calculate", expression="2+3")])
        model = agents.store.model(conv.model_id)
        assert capability(agents.service, model)["status"] == "unverified"
        result = await agents.test_compatibility(model.id, protocol="structured")
        assert result["status"] == "json" and result["tested"]
        restarted = Agents(agents.service)
        assert capability(restarted.service, model)["tested"]
        before = cache_key(agents.service, model)
        agents.service.config.llama_chat_template = "changed-template"
        assert cache_key(agents.service, model) != before
        assert not capability(agents.service, model)["tested"]
        assert engine.messages and not agents.store.jobs("agent-run")
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "response",
    [FINAL, "not JSON", '{"kind":"tool","name":"calculate","arguments":{"expression":4}}'],
)
def test_unsupported_model_test_and_malformed_metadata(tmp_path, response):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [response])
        model = agents.store.model(conv.model_id)
        model.metadata = {"metadata": ["bad"], "chat_template": 42}
        agents.store.update_model(model)
        assert capability(agents.service, model)["status"] == "unverified"
        assert not capability(agents.service, model)["template_available"]
        result = await agents.test_compatibility(model.id)
        assert result["status"] == "unsupported" and result["tested"]
        with pytest.raises(TextError, match="agent_model_unsupported"):
            await agents.submit(conv.id, AgentRequest(content="task"))
        assert not agents.service.history.messages(conv.id)
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_gguf_template_is_read_without_guessing_capabilities(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [])
        # Insert a bounded metadata string in the synthetic fixture (not model weights).
        data = synthetic_gguf()
        key, value = b"tokenizer.chat_template", b"{{ tools }} [tool_call]"
        item = struct.pack("<Q", len(key)) + key + struct.pack("<IQ", 8, len(value)) + value
        name = b"test.weight"
        offset = data.index(struct.pack("<Q", len(name)) + name)
        header = data[:16] + struct.pack("<Q", 4) + data[24:offset] + item
        tensor = data[offset : offset + 8 + len(name) + 24]
        packed = header + tensor
        path = tmp_path / "models" / "template.gguf"
        path.write_bytes(packed + b"\0" * (-len(packed) % 32) + struct.pack("<ffff", 0, 0, 0, 0))
        imported = agents.service.models.import_gguf(path)
        info = capability(agents.service, imported)
        assert info["template_available"] and info["status"] == "unverified"
        assert imported.metadata["metadata"]["tokenizer.chat_template"] == value.decode()
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("with_id", [True, False])
def test_native_ollama_text_calls_and_duplicate_id_execute_once(tmp_path, with_id):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [])
        model = agents.store.model(conv.model_id)
        model.backend, model.location, model.capabilities = "ollama", "test:tools", ["tool-calling"]
        agents.store.update_model(model)
        seen = []

        def response(request):
            if request.url.path == "/api/version":
                return httpx.Response(200, json={"version": "test-v1"})
            if request.url.path == "/api/generate":
                return httpx.Response(200, json={"done": True})
            body = json.loads(request.content)
            assert any(t["function"]["name"] == "set_plan" for t in body["tools"])
            seen.append(body)
            call = {
                "id": "same-call",
                "function": {"name": "calculate", "arguments": {"expression": "2+3"}},
            }
            if not with_id:
                call.pop("id")
            if body["messages"][0]["content"].startswith("Call calculate"):
                return httpx.Response(
                    200,
                    json={
                        "done": True,
                        "done_reason": "stop",
                        "message": {
                            "content": "",
                            "tool_calls": [call],
                        },
                    },
                )
            message = (
                {"role": "assistant", "content": "Calculating", "tool_calls": [call, call]}
                if len(seen) == 1
                else {"role": "assistant", "content": "Five"}
            )
            return httpx.Response(
                200, json={"done": True, "done_reason": "stop", "message": message}
            )

        async with httpx.AsyncClient(
            base_url="http://localhost", transport=httpx.MockTransport(response)
        ) as client:
            agents.service.engines["ollama"] = OllamaEngine(client=client)
            info = capability(agents.service, model)
            assert info["status"] == "native" and not info["tested"]
            result = await finish(agents, conv)
            assert result["state"] == "completed" and len(result["steps"]) == 1
            assert result["tool_mode"] == "native" and result["duplicate_calls"] == 1
            assert "replayed" in seen[1]["messages"][-1]["content"]
            tested = await agents.test_compatibility(model.id)
            assert tested["status"] == "native" and tested["tested"]
            assert tested["backend_version"] == "test-v1"
            await agents.close()
            await agents.service.generations.close()

    asyncio.run(exercise())


def test_one_json_repair_then_multistep_plan_correction(tmp_path):
    async def exercise():
        plan = json.dumps(
            {
                "kind": "plan",
                "steps": [
                    {"id": "calc", "title": "Calculate"},
                    {"id": "unused", "title": "Old step"},
                ],
            }
        )
        revised = json.dumps(
            {
                "kind": "plan",
                "steps": [
                    {"id": "calc", "title": "Already calculated"},
                    {"id": "next", "title": "Calculate again"},
                ],
            }
        )
        agents, conv, engine = setup(
            tmp_path,
            [
                "{",
                plan,
                tool("calculate", expression="2+3"),
                revised,
                tool("calculate", expression="3+4"),
                FINAL,
            ],
        )
        result = await finish(agents, conv)
        assert result["state"] == "completed" and result["protocol_retries"] == 1
        assert result["plan_revisions"] == 2
        assert result["plan"][0]["title"] == "Calculate"
        assert [p["id"] for p in result["plan"]] == ["calc", "next"]
        assert all(p["state"] == "completed" for p in result["plan"])
        assert len(result["steps"]) == 2
        assert all(p.max_tokens == 256 for p in [agents.service.history.get(conv.id).parameters])
        assert len(engine.messages) == 6
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "response", [tool("calculate", expression="1") * 2, "text " + tool("calculate", expression="1")]
)
def test_repeated_or_prose_stream_does_not_execute_before_repair(tmp_path, response):
    async def exercise():
        valid = json.dumps(
            {
                "kind": "tool",
                "name": "calculate",
                "arguments": {"expression": "1"},
                "text": "Calculating now",
                "call_id": "one",
            }
        )
        agents, conv, _ = setup(tmp_path, [response, valid, FINAL])
        result = await finish(agents, conv)
        assert result["state"] == "completed" and len(result["steps"]) == 1
        assert result["protocol_retries"] == 1
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_duplicate_call_loop_is_bounded(tmp_path):
    async def exercise():
        response = json.dumps(
            {
                "kind": "tool",
                "name": "calculate",
                "arguments": {"expression": "1"},
                "call_id": "replay",
            }
        )
        agents, conv, _ = setup(tmp_path, [response] * 20)
        result = await finish(agents, conv)
        assert result["error_code"] == "agent_turn_limit"
        assert len(result["steps"]) == 1 and result["duplicate_calls"] == 12
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("approve", [True, False])
def test_retry_protects_written_and_denied_targets_even_with_new_grant(tmp_path, approve):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [])
        grant = agents.files.grant(conv.id, tmp_path)
        write = tool(
            "write_text", grant_id=grant["id"], path="result.txt", mode="create", content="first"
        )
        engine.responses = iter([write, write, "invalid", "invalid"])
        first = await agents.submit(conv.id, AgentRequest(content="write"))
        task = agents.tasks[first["id"]]
        step = await waiting(agents, first["id"])
        agents.approve(first["id"], step["id"], step["proposal_id"], approve)
        await task
        assert agents.record(first["id"])["state"] == "failed"
        assert agents.record(first["id"])["steps"][1]["error_code"] == "agent_write_replay_blocked"
        agents.files.revoke(grant["id"], conv.id)
        grant = agents.files.grant(conv.id, tmp_path)
        engine.responses = iter(
            [
                tool(
                    "write_text",
                    grant_id=grant["id"],
                    path="result.txt",
                    mode="create",
                    content="changed by retry",
                ),
                FINAL,
            ]
        )
        second = await agents.retry(first["id"])
        await agents.tasks[second["id"]]
        saved = agents.record(second["id"])
        assert saved["steps"][0]["error_code"] == "agent_write_replay_blocked"
        assert not agents.approvals
        target = tmp_path / "result.txt"
        assert target.read_text() == "first" if approve else not target.exists()
        assert saved["family"] == first["id"]
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_context_is_bounded_and_summaries_omit_old_file_contents():
    parameters = GenerationParameters(context_size=2048)
    base = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "current task"},
        {"role": "user", "content": "grants"},
    ]
    rounds = [[{"role": "user", "content": f"old-{i}" + "X" * 500}] for i in range(6)]
    record = {
        "steps": [{"tool": "read_text", "state": "completed", "result_summary": {"bytes": 12}}]
    }
    messages = messages_for_turn(base, rounds, record, parameters)
    assert not any("old-0" in m["content"] for m in messages)
    assert any("old-5" in m["content"] for m in messages)
    assert record["context"]["approx_tokens"] + 256 <= 2048
    result = bounded_result({"text": "ż" * 5000})
    assert result["truncated"] and result["original_bytes"] == 10000
    assert len(result["text"].encode()) <= 4096


def test_plan_limits_and_invalid_arguments_detail(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [tool("calculate", expression=5), FINAL])
        result = await finish(agents, conv)
        details = result["steps"][0]["error_details"]
        assert details == [{"field": "expression", "type": "string_type"}]
        assert "input" not in json.dumps(details)
        update = PlanUpdate(kind="plan", steps=[{"id": "x", "title": "Work"}])
        for _ in range(3):
            agents.update_plan(result, update, 8)
        with pytest.raises(TextError, match="agent_plan_limit"):
            agents.update_plan(result, update, 8)
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_malformed_native_request_and_plain_final_are_distinct():
    assert parse_turn({"content": "ordinary answer"}, True).text == "ordinary answer"
    with pytest.raises(TextError, match="agent_protocol_invalid"):
        parse_turn({"content": "answer", "tool_calls": "not an array"}, True)


def test_http_compatibility_is_opt_in_and_retry_is_new_attempt(client, app):
    from test_agents import ScriptedEngine

    service = app.state.text
    models = service.config.data_dir / "models"
    models.mkdir(exist_ok=True)
    path = models / "agent.gguf"
    path.write_bytes(synthetic_gguf())
    model = service.models.import_gguf(path)
    engine = ScriptedEngine([tool("calculate", expression="2+3")])
    service.engines["llama.cpp"] = engine
    base = f"/api/v1/agents/models/{model.id}"
    assert client.get(base + "/compatibility").json()["status"] == "unverified"
    assert engine.messages == []
    assert client.post(base + "/compatibility-test", json={}).status_code == 422
    assert engine.messages == []
    assert (
        client.post(base + "/compatibility-test", json={"confirmed": True}).json()["status"]
        == "json"
    )
    assert client.get(base + "/compatibility").json()["tested"]
    assert client.post("/api/v1/agents/runs/missing/retry").status_code == 404


def test_probe_timeout_does_not_label_model_unsupported(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [""], wait=True)
        agents.service.config.generation_timeout = 0.01
        result = await agents.test_compatibility(conv.model_id)
        assert result["status"] == "unverified" and not result["tested"]
        assert result["error_code"] == "agent_timeout"
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())
