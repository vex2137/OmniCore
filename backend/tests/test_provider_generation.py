import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_providers import MemoryVault, service

from omnicore.app import create_app
from omnicore.providers.service import CloudEngine, ProviderInput
from omnicore.providers.vault import SystemVault
from omnicore.text.types import GenerationParameters, TextError, TextMessage


def test_cloud_models_use_existing_history_jobs_titles_and_no_implicit_fallback(config):
    app = create_app(replace(config, api_token="a" * 64, ollama_enabled=False))
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        text = (
            "Conversation about OmniCore RC.5 provider configuration and streaming details"
            if body["max_completion_tokens"] == 32
            else "Cloud answer"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: "
            + json.dumps(
                {
                    "choices": [{"delta": {"content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                }
            )
            + "\n\n",
        )

    owner = {"Authorization": "Bearer " + "a" * 64}
    with TestClient(
        app, base_url="http://localhost", client=("127.0.0.1", 1234), headers=owner
    ) as c:
        providers = app.state.text.providers
        providers.vault = MemoryVault()
        providers.transport = httpx.MockTransport(handler)
        config = c.post(
            "/api/v1/providers/configs", json={"kind": "openai", "api_key": "test-provider-secret"}
        ).json()
        assert requests == []
        assert (
            c.post(
                f"/api/v1/providers/configs/{config['id']}/models",
                json={"model_id": "controlled-chat"},
            ).status_code
            == 422
        )
        model = c.post(
            f"/api/v1/providers/configs/{config['id']}/models",
            json={"model_id": "controlled-chat", "confirmed_external": True},
        ).json()
        assert model["backend"] == "cloud" and requests == []
        chat = c.post(
            "/api/v1/text/conversations",
            json={"model_id": model["id"], "parameters": {"device": "cuda", "gpu_layers": 25}},
        ).json()
        job = c.post(
            f"/api/v1/text/conversations/{chat['id']}/generations",
            json={"content": "Explain provider streaming", "request_key": "cloud-only"},
        ).json()
        for _ in range(200):
            saved = c.get(f"/api/v1/text/generations/{job['id']}").json()
            title = c.get(f"/api/v1/text/conversations/{chat['id']}").json()
            if saved["state"] == "completed" and title["title_status"] == "completed":
                break
            time.sleep(0.01)
        assert saved["state"] == "completed" and saved["content"] == "Cloud answer"
        assert (
            saved["execution_provider"] == "openai"
            and saved["execution_model"] == "controlled-chat"
        )
        assert saved["execution_device"] is None and saved["context_limit_tokens"] is None
        assert saved["input_tokens"] == 10 and saved["output_tokens"] == 3
        assert title["title"] == "OmniCore RC.5 provider configuration and"
        assert title["parameters"]["device"] == "cuda"
        assert len(requests) == 2
        assert all(
            "gpu_layers" not in json.loads(r.content) and "device" not in json.loads(r.content)
            for r in requests
        )
        messages = c.get(f"/api/v1/text/conversations/{chat['id']}/messages").json()
        assert messages[-1]["statistics"]["execution_provider"] == "openai"
        assert "test-provider-secret" not in str(messages)


def test_cloud_stream_cancellation_closes_network_response(tmp_path):
    class Stream(httpx.AsyncByteStream):
        def __init__(self):
            self.closed = False
            self.reading = asyncio.Event()

        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"First"}}]}\n\n'
            self.reading.set()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    async def exercise():
        stream = Stream()
        manager = service(
            tmp_path,
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            ),
        )
        info = manager.save(ProviderInput(kind="openai", api_key="test-provider-secret"))
        model = manager.add_model(info.id, "controlled-chat")
        engine = CloudEngine(manager)

        async def consume():
            async for _ in engine.stream(
                model.location,
                [TextMessage(role="user", content="Question")],
                GenerationParameters(),
            ):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(stream.reading.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and not engine.clients

    asyncio.run(exercise())


def test_unavailable_os_vault_never_falls_back_to_plaintext(tmp_path, monkeypatch):
    manager = service(tmp_path, lambda request: httpx.Response(500))
    manager.vault = SystemVault(tmp_path)

    def unavailable():
        raise RuntimeError("No OS secret service")

    monkeypatch.setattr(manager.vault, "backend", unavailable)
    with pytest.raises(TextError, match="provider_secret_store_unavailable"):
        manager.save(ProviderInput(kind="openai", api_key="test-provider-secret"))
    assert manager.list() == []
