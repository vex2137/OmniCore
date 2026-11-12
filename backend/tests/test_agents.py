"""Agent integration uses synthetic GGUF headers and a controlled engine, not real inference."""

import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from test_text_generation import ProtocolTestEngine, create_manager

from omnicore.agents.model import AgentModel
from omnicore.agents.service import AgentRequest, Agents, AgentSettings, parse_turn
from omnicore.agents.tools import FileArgs, FileTools, FindArgs, WriteArgs, calculate
from omnicore.text.conversations import Conversations
from omnicore.text.generation import GenerationRequest
from omnicore.text.types import GenerationParameters, TextChunk, TextError


def tool(name, **arguments):
    return json.dumps({"kind": "tool", "name": name, "arguments": arguments})


FINAL = json.dumps({"kind": "final", "text": "Done"})


class ScriptedEngine(ProtocolTestEngine):
    def __init__(self, responses, *, finish="stop", wait=False):
        super().__init__(wait=wait)
        self.responses = iter(responses)
        self.messages = []
        self.finish = finish

    async def stream(self, model, messages, parameters):
        self.messages.append(messages)
        response = next(self.responses)
        # A tool must never run from this incomplete first fragment.
        yield TextChunk(content=response[:8])
        self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        yield TextChunk(content=response[8:], finish_reason=self.finish)


def setup(tmp_path, responses, **engine_options):
    engine = ScriptedEngine(responses, **engine_options)
    manager, conversation = create_manager(tmp_path, engine)
    service = SimpleNamespace(
        store=manager.store,
        models=manager.models,
        engines=manager.engines,
        generations=manager,
        history=Conversations(manager.store),
        config=SimpleNamespace(generation_timeout=2),
    )
    agents = Agents(service)
    manager.external_busy = agents.active_for

    def idle(**scope):
        if manager.active_for(**scope) or agents.active_for(**scope):
            raise TextError("conversation_busy", 409)

    service.require_idle = idle
    service.store.save_job(
        "agent-settings", conversation.id, AgentSettings(mode="agent").model_dump()
    )
    return agents, conversation, engine


async def finish(agents, conversation):
    record = await agents.submit(conversation.id, AgentRequest(content="Use tools"))
    await agents.tasks[record["id"]]
    return agents.record(record["id"])


async def waiting(agents, run_id):
    async with asyncio.timeout(3):
        while True:
            snapshot = agents.snapshot(run_id)
            if snapshot["steps"] and snapshot["steps"][-1]["state"] == "waiting":
                return snapshot["steps"][-1]
            await asyncio.sleep(0.005)


def test_read_calculate_and_history_redaction(tmp_path):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [])
        folder = tmp_path / "shared"
        folder.mkdir()
        (folder / "notes.txt").write_text("PRIVATE_CONTENT_123\nżółć", encoding="utf-8")
        grant = agents.files.grant(conv.id, folder)
        engine.responses = iter(
            [
                tool("read_text", grant_id=grant["id"], path="notes.txt"),
                tool("calculate", expression="(2 + 3) * 7"),
                FINAL,
            ]
        )
        result = await finish(agents, conv)
        assert result["state"] == "completed"
        assert [step["state"] for step in result["steps"]] == ["completed", "completed"]
        assert result["steps"][1]["result_summary"] == {"value": 35}
        assert "PRIVATE_CONTENT_123" in engine.messages[1][-1].content
        assert "PRIVATE_CONTENT_123" not in json.dumps(agents.store.jobs("agent-run"))
        assert agents.service.history.messages(conv.id)[-1].content == "Done"
        restarted = Agents(agents.service)
        restarted.initialize()
        assert restarted.settings(conv.id).mode == "agent"
        assert restarted.record(result["id"])["steps"] == result["steps"]
        assert not restarted.files.grants
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("approve", [True, False])
@pytest.mark.parametrize("mode", ["create", "edit"])
def test_write_preview_approval_and_rejection(tmp_path, approve, mode):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [])
        folder = tmp_path / "shared"
        folder.mkdir()
        target = folder / "result.txt"
        if mode == "edit":
            target.write_text("before\n")
        grant = agents.files.grant(conv.id, folder)
        engine.responses = iter(
            [
                tool(
                    "write_text",
                    grant_id=grant["id"],
                    path=target.name,
                    mode=mode,
                    content="after\n",
                ),
                FINAL,
            ]
        )
        record = await agents.submit(conv.id, AgentRequest(content="Change file"))
        task = agents.tasks[record["id"]]
        step = await waiting(agents, record["id"])
        assert "+after" in step["diff"]
        assert not target.exists() if mode == "create" else target.read_text() == "before\n"
        with pytest.raises(TextError, match="agent_approval_expired"):
            agents.approve(record["id"], step["id"], "wrong", True)
        agents.approve(record["id"], step["id"], step["proposal_id"], approve)
        with pytest.raises(TextError, match="agent_approval_expired"):
            agents.approve(record["id"], step["id"], step["proposal_id"], approve)
        await task
        saved = agents.record(record["id"])
        assert saved["state"] == "completed"
        assert saved["steps"][0]["state"] == ("completed" if approve else "cancelled")
        if approve:
            assert target.read_text() == "after\n"
            if mode == "edit":
                backup = saved["steps"][0]["result_summary"]["backup"]
                assert (folder / backup).read_text() == "before\n"
        elif mode == "create":
            assert not target.exists()
        else:
            assert target.read_text() == "before\n"
        assert "after\\n" not in json.dumps(saved)
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("response", ["ordinary text: delete file", "{", "[1]", '{"kind":"tool"}'])
def test_invalid_or_unsupported_model_never_executes(tmp_path, response):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [response, response])
        result = await finish(agents, conv)
        assert result["state"] == "failed"
        assert result["error_code"] == "agent_protocol_invalid"
        assert result["steps"] == []
        assert result["protocol_retries"] == 1
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_incomplete_stream_is_not_a_tool_call(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [tool("calculate", expression="1+1")], finish="length")
        result = await finish(agents, conv)
        assert result["error_code"] == "agent_incomplete_response"
        assert not result["steps"]
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (tool("terminal", command="ls"), "agent_unknown_tool"),
        (tool("calculate", expression=12), "agent_invalid_arguments"),
        (tool("calculate", expression="1", extra=True), "agent_invalid_arguments"),
    ],
)
def test_invalid_tool_and_arguments(tmp_path, response, code):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [response, FINAL])
        result = await finish(agents, conv)
        assert result["steps"][0]["error_code"] == code
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_step_limit(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [tool("calculate", expression="1")] * 3)
        agents.store.save_job(
            "agent-settings", conv.id, AgentSettings(mode="agent", max_steps=2).model_dump()
        )
        result = await finish(agents, conv)
        assert result["error_code"] == "agent_step_limit"
        assert len(result["steps"]) == 2
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_cancel_mid_stream_and_chat_mutual_exclusion(tmp_path):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [tool("calculate", expression="1")], wait=True)
        record = await agents.submit(conv.id, AgentRequest(content="calculate"))
        await engine.started.wait()
        with pytest.raises(TextError, match="conversation_busy"):
            await agents.service.generations.submit(
                conv.id, GenerationRequest(content="chat", request_key="parallel")
            )
        await agents.cancel(record["id"])
        assert agents.record(record["id"])["state"] == "cancelled"
        assert not agents.record(record["id"])["steps"]
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_cancel_approval_and_restart_never_writes(tmp_path):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [])
        grant = agents.files.grant(conv.id, tmp_path)
        engine.responses = iter(
            [tool("write_text", grant_id=grant["id"], path="new.txt", mode="create", content="new")]
        )
        record = await agents.submit(conv.id, AgentRequest(content="write"))
        step = await waiting(agents, record["id"])
        restarted = Agents(agents.service)
        restarted.initialize()
        saved = restarted.record(record["id"])
        assert saved["state"] == "interrupted"
        assert saved["steps"][0]["state"] == "interrupted"
        assert not restarted.files.grants
        with pytest.raises(TextError, match="agent_approval_expired"):
            restarted.approve(record["id"], step["id"], step["proposal_id"], True)
        await agents.cancel(record["id"])
        assert not (tmp_path / "new.txt").exists()
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_tool_timeout_and_revoke(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [tool("calculate", expression="1"), FINAL])
        agents.tool_timeout = 0.01
        token = threading.Event()
        started = threading.Event()

        def blocked(*_):
            started.set()
            token.wait(1)
            return {"text": "private"}

        agents.files.read = blocked
        record = {"id": "test", "conversation_id": conv.id, "state": "running", "steps": []}
        result = await agents.execute(
            record, parse_turn(tool("read_text", grant_id="x", path="x"), False)[0], token
        )
        assert started.is_set() and token.is_set()
        assert result == {"error": "agent_tool_timeout"}
        assert record["steps"][0]["state"] == "failed"
        grant = agents.files.grant(conv.id, tmp_path)
        agents.files.revoke(grant["id"], conv.id)
        with pytest.raises(TextError, match="agent_permission_denied"):
            agents.files.get(grant["id"], conv.id)
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


@pytest.fixture
def files(tmp_path):
    tools = FileTools()
    grant = tools.grant("conversation", tmp_path)
    yield tools, grant["id"], threading.Event()
    tools.close()


@pytest.mark.parametrize(
    "path",
    ["../outside", "/etc/passwd", "a/../../secret", "a\\b", ".env", "private.key", "signing.json"],
)
def test_file_boundaries_and_sensitive_opt_in(files, path):
    tools, grant, cancelled = files
    with pytest.raises((TextError, OSError)):
        tools.read("read_text", FileArgs(grant_id=grant, path=path), "conversation", cancelled)


def test_symlink_hardlink_and_cross_conversation(files, tmp_path):
    tools, grant, cancelled = files
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    (tmp_path / "link").symlink_to(outside)
    (tmp_path / "folder").symlink_to(tmp_path.parent, target_is_directory=True)
    (tmp_path / "hard").hardlink_to(outside)
    for path in ("link", "folder/outside.txt", "hard"):
        with pytest.raises((TextError, OSError)):
            tools.read("read_text", FileArgs(grant_id=grant, path=path), "conversation", cancelled)
    with pytest.raises(TextError, match="agent_permission_denied"):
        tools.read("list_files", FileArgs(grant_id=grant), "other", cancelled)
    names = tools.read("list_files", FileArgs(grant_id=grant), "conversation", cancelled)
    assert not {"link", "folder"} & {entry["path"] for entry in names["entries"]}


def test_list_search_stat_and_read_limit(files, tmp_path):
    tools, grant, cancelled = files
    (tmp_path / "doc.txt").write_text("żółć", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "doc2.txt").write_text("x")
    found = tools.read(
        "find_files", FindArgs(grant_id=grant, query="doc"), "conversation", cancelled
    )
    assert len(found["entries"]) == 2
    info = tools.read(
        "file_info", FileArgs(grant_id=grant, path="doc.txt"), "conversation", cancelled
    )
    assert info["size"] == 8 and info["extension"] == ".txt"
    (tmp_path / "big.txt").write_bytes(b"x" * 65537)
    with pytest.raises(TextError, match="agent_file_limit"):
        tools.read("read_text", FileArgs(grant_id=grant, path="big.txt"), "conversation", cancelled)


def test_write_conflict_and_replaced_symlink(files, tmp_path):
    tools, grant, cancelled = files
    target = tmp_path / "doc.txt"
    target.write_text("before")
    proposal = tools.propose(
        WriteArgs(grant_id=grant, path=target.name, mode="edit", content="after"),
        "conversation",
        cancelled,
    )
    target.write_text("other writer")
    with pytest.raises(TextError, match="agent_file_conflict"):
        tools.commit(proposal, cancelled)
    assert target.read_text() == "other writer"
    target.unlink()
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    target.symlink_to(outside)
    with pytest.raises(OSError):
        tools.commit(proposal, cancelled)
    assert outside.read_text() == "outside"


def test_exchange_detects_race_and_restores_other_writer(files, tmp_path, monkeypatch):
    tools, grant, cancelled = files
    target = tmp_path / "doc.txt"
    target.write_text("before")
    proposal = tools.propose(
        WriteArgs(grant_id=grant, path=target.name, mode="edit", content="after"),
        "conversation",
        cancelled,
    )
    original = tools.exchange
    calls = []

    def racing(parent, first, second):
        if not calls:
            target.write_text("concurrent")
        calls.append(1)
        return original(parent, first, second)

    monkeypatch.setattr(tools, "exchange", racing)
    with pytest.raises(TextError, match="agent_file_conflict"):
        tools.commit(proposal, cancelled)
    assert target.read_text() == "concurrent"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "expression", ['__import__("os").system("id")', "2**99999", "[1,2]", "True", "1/0"]
)
def test_arithmetic_cannot_execute_code(expression):
    with pytest.raises((TextError, ValueError, ZeroDivisionError)):
        calculate(expression)


def test_native_ollama_complete_tool_calls_and_parameters():
    async def exercise():
        def reply(request):
            body = json.loads(request.content)
            assert body["tools"] and body["stream"] is False
            assert body["options"]["num_ctx"] == 8192
            assert body["options"]["num_predict"] == 512
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "done_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "calculate", "arguments": {"expression": "2+2"}}}
                        ],
                    },
                },
            )

        async with httpx.AsyncClient(
            base_url="http://localhost", transport=httpx.MockTransport(reply)
        ) as client:
            result, native = await AgentModel(None).ollama(
                SimpleNamespace(client=client),
                "test",
                [],
                GenerationParameters(context_size=8192, max_tokens=512),
            )
        assert native
        assert parse_turn(result, native)[0].name == "calculate"

    asyncio.run(exercise())


def test_http_approval_and_permission_boundary(client, app, tmp_path):
    import time

    from test_text_models import synthetic_gguf

    service = app.state.text
    models = service.config.data_dir / "models"
    models.mkdir(exist_ok=True)
    model_file = models / "agent.gguf"
    model_file.write_bytes(synthetic_gguf())
    model = service.models.import_gguf(model_file)
    conversation = service.history.create(model_id=model.id)
    base = f"/api/v1/agents/conversations/{conversation.id}"
    assert client.get(base + "/settings").json()["mode"] == "chat"
    assert client.post(base + "/runs", json={"content": "hi"}).status_code == 409
    assert client.post(base + "/folders", json={"path": str(tmp_path)}).status_code == 422
    grant = client.post(base + "/folders", json={"path": str(tmp_path), "confirmed": True}).json()
    assert client.put(base + "/settings", json={"mode": "agent"}).status_code == 200
    engine = ScriptedEngine(
        [
            tool(
                "write_text",
                grant_id=grant["id"],
                path="approved.txt",
                mode="create",
                content="approved",
            ),
            FINAL,
        ]
    )
    service.engines["llama.cpp"] = engine
    run = client.post(base + "/runs", json={"content": "create text"}).json()
    run_path = f"/api/v1/agents/runs/{run['id']}"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = client.get(run_path).json()
        if current["steps"] and current["steps"][0]["state"] == "waiting":
            break
        time.sleep(0.005)
    else:
        pytest.fail("Write approval was not exposed by the API")
    step = current["steps"][0]
    approval_path = run_path + f"/steps/{step['id']}/approval"
    assert (
        client.post(approval_path, json={"proposal_id": "bad", "approved": True}).status_code == 409
    )
    assert not (tmp_path / "approved.txt").exists()
    assert (
        client.post(
            approval_path, json={"proposal_id": step["proposal_id"], "approved": True}
        ).status_code
        == 200
    )
    while time.monotonic() < deadline:
        current = client.get(run_path).json()
        if current["state"] in {"failed", "completed"}:
            break
        time.sleep(0.005)
    assert current["state"] == "completed"
    assert (tmp_path / "approved.txt").read_text() == "approved"
    assert client.delete(base + f"/folders/{grant['id']}").status_code == 200
    assert client.get(base + "/folders").json() == []
    assert client.get(base + "/runs").json()[0]["id"] == run["id"]


def test_deleted_conversation_removes_agent_audit_and_settings(tmp_path):
    async def exercise():
        agents, conv, _ = setup(tmp_path, [tool("calculate", expression="2+2"), FINAL])
        result = await finish(agents, conv)
        agents.service.history.delete(conv.id)
        with pytest.raises(TextError, match="not_found"):
            agents.record(result["id"])
        assert agents.store.jobs("agent-settings") == []
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())


def test_approval_does_not_survive_real_service_restart(tmp_path):
    from test_text_models import synthetic_gguf

    from omnicore.config import RuntimeConfig
    from omnicore.database import Database
    from omnicore.events import EventHub
    from omnicore.text.api import TextService

    async def exercise():
        config = RuntimeConfig(data_dir=tmp_path / "data")
        database = Database(config.data_dir)
        database.initialize()
        first = TextService(database, config, EventHub())
        first.initialize()
        folder = config.data_dir / "models"
        folder.mkdir(exist_ok=True)
        path = folder / "test.gguf"
        path.write_bytes(synthetic_gguf())
        model = first.models.import_gguf(path)
        conv = first.history.create(model_id=model.id)
        first.store.save_job("agent-settings", conv.id, AgentSettings(mode="agent").model_dump())
        grant = first.agents.files.grant(conv.id, tmp_path)
        first.engines["llama.cpp"] = ScriptedEngine(
            [
                tool(
                    "write_text",
                    grant_id=grant["id"],
                    path="never.txt",
                    mode="create",
                    content="no",
                ),
            ]
        )
        run = await first.agents.submit(conv.id, AgentRequest(content="write"))
        await waiting(first.agents, run["id"])
        await first.close()
        second = TextService(database, config, EventHub())
        second.initialize()
        assert second.agents.settings(conv.id).mode == "agent"
        assert second.agents.record(run["id"])["state"] == "cancelled"
        assert second.history.messages(conv.id)[0].content == "write"
        assert second.models.validated_reference(model.id) == path
        assert not second.agents.files.grants and not second.agents.tasks
        assert not (tmp_path / "never.txt").exists()
        await second.close()

    asyncio.run(exercise())


def test_cancel_acknowledges_approved_commit_before_return(tmp_path, monkeypatch):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [])
        grant = agents.files.grant(conv.id, tmp_path)
        engine.responses = iter(
            [
                tool(
                    "write_text",
                    grant_id=grant["id"],
                    path="saved.txt",
                    mode="create",
                    content="approved",
                ),
                FINAL,
            ]
        )
        entered, release = threading.Event(), threading.Event()
        commit = agents.files.commit

        def slow_commit(proposal, cancelled):
            with agents.files.write_lock:
                entered.set()
                assert release.wait(2)
                return commit(proposal, cancelled)

        monkeypatch.setattr(agents.files, "commit", slow_commit)
        record = await agents.submit(conv.id, AgentRequest(content="write"))
        step = await waiting(agents, record["id"])
        agents.approve(record["id"], step["id"], step["proposal_id"], True)
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        cancellation = asyncio.create_task(agents.cancel(record["id"]))
        await asyncio.sleep(0.01)
        assert not cancellation.done()
        release.set()
        await cancellation
        assert (tmp_path / "saved.txt").read_text() == "approved"
        saved = agents.record(record["id"])
        assert saved["steps"][0]["state"] == "completed"
        assert saved["steps"][0]["result_summary"]["written"] is True
        assert not agents.active_for(conversation_id=conv.id)
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())
