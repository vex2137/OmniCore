import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.database import Database
from omnicore.providers.service import CloudEngine, ProviderInput, Providers, endpoint_for
from omnicore.text.store import TextStore
from omnicore.text.types import GenerationParameters, TextError, TextMessage


class MemoryVault:
    def __init__(self):
        self.secrets = {}

    def put(self, ref, value):
        self.secrets[ref] = value

    def get(self, ref):
        return self.secrets[ref]

    def delete(self, ref):
        self.secrets.pop(ref, None)


def service(tmp_path, handler):
    db = Database(tmp_path)
    db.initialize()
    store = TextStore(db)
    store.initialize()
    manager = Providers(store, vault=MemoryVault(), transport=httpx.MockTransport(handler))
    manager.initialize()
    return manager


def stream_body(kind):
    if kind == "anthropic":
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            },
        ]
    elif kind == "gemini":
        events = [
            {
                "candidates": [{"content": {"parts": [{"text": "Hello"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            }
        ]
    else:
        events = [
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        ]
    return "".join("data: " + json.dumps(e) + "\n\n" for e in events)


@pytest.mark.parametrize("kind", ["openai", "anthropic", "gemini", "openrouter", "custom"])
def test_provider_model_list_auth_stream_usage_and_distinct_wire_shapes(tmp_path, kind):
    requests = []

    def handler(request):
        requests.append(request)
        assert "test-provider-secret" not in str(request.url)
        if request.method == "GET":
            body = (
                {
                    "models": [
                        {
                            "name": "models/controlled-chat",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                }
                if kind == "gemini"
                else {"data": [{"id": "controlled-chat"}]}
            )
            return httpx.Response(200, json=body)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=stream_body(kind)
        )

    manager = service(tmp_path, handler)
    info = manager.save(
        ProviderInput(
            kind=kind,
            endpoint="https://custom.example/v1" if kind == "custom" else "",
            api_key="test-provider-secret",
            sampling=True,
        )
    )

    async def exercise():
        models = await manager.models(info.id)
        model = manager.add_model(info.id, models[0])
        engine = CloudEngine(manager)
        chunks = [
            chunk
            async for chunk in engine.stream(
                model.location,
                [
                    TextMessage(role="system", content="Instructions"),
                    TextMessage(role="user", content="Question"),
                ],
                GenerationParameters(),
            )
        ]
        assert "".join(c.content for c in chunks) == "Hello"
        assert next(c for c in chunks if c.input_tokens is not None).input_tokens == 5
        assert next(c for c in chunks if c.output_tokens is not None).output_tokens == 2
        assert all(c.execution_device is None and c.gpu_offloaded_layers is None for c in chunks)
        assert chunks[0].execution_provider == kind
        body = json.loads(requests[-1].content)
        assert requests[-1].url.path.endswith(
            {
                "anthropic": "/messages",
                "gemini": "/models/controlled-chat:streamGenerateContent",
            }.get(kind, "/chat/completions")
        )
        header = (
            "x-api-key"
            if kind == "anthropic"
            else "x-goog-api-key"
            if kind == "gemini"
            else "authorization"
        )
        assert "test-provider-secret" in requests[-1].headers[header]
        if kind == "gemini":
            assert body["contents"][0]["role"] == "user" and body["systemInstruction"]
        elif kind == "anthropic":
            assert body["system"] == "Instructions" and body["max_tokens"] == 256
        else:
            assert body["messages"][0]["role"] == "system"
        assert info.key_present and "test-provider-secret" not in info.model_dump_json()
        await engine.stop()

    asyncio.run(exercise())
    with manager.store.db.connect() as c:
        assert "test-provider-secret" not in str(
            c.execute("SELECT record FROM ai_providers").fetchall()
        )


@pytest.mark.parametrize(
    "status,code",
    [(401, "provider_auth_failed"), (429, "provider_rate_limited"), (503, "provider_unavailable")],
)
def test_provider_errors_are_bounded_and_never_echo_secret(tmp_path, status, code):
    manager = service(
        tmp_path, lambda request: httpx.Response(status, text="test-provider-secret private prompt")
    )
    info = manager.save(ProviderInput(kind="openai", api_key="test-provider-secret"))

    async def exercise():
        with pytest.raises(TextError, match=code) as failure:
            await manager.models(info.id)
        assert "secret" not in str(failure.value) and "prompt" not in str(failure.value)

    asyncio.run(exercise())


def test_secret_destination_changes_require_reentry_and_clear_removes_key(tmp_path):
    manager = service(tmp_path, lambda request: httpx.Response(200, json={"data": []}))
    info = manager.save(
        ProviderInput(
            kind="custom", endpoint="https://first.example/v1", api_key="test-provider-secret"
        )
    )
    with pytest.raises(TextError, match="provider_key_reentry_required"):
        manager.save(ProviderInput(kind="custom", endpoint="https://second.example/v1"), info.id)
    assert len(manager.vault.secrets) == 1
    manager.save(ProviderInput(kind="custom", endpoint=info.endpoint, clear_key=True), info.id)
    assert manager.vault.secrets == {}
    assert not manager.list()[0].key_present


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example/v1",
        "https://key@public.example",
        "https://public.example?key=secret",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://localhost",
        "https://192.168.1.2",
    ],
)
def test_custom_endpoint_rejects_credentials_and_internal_destinations(url):
    with pytest.raises(TextError, match="provider_endpoint_invalid"):
        endpoint_for("custom", url)


def test_provider_key_transfer_requires_tls_for_lan_and_management_scope(config):
    from dataclasses import replace

    app = create_app(replace(config, allow_remote=True, api_token="a" * 64))
    with TestClient(app, base_url="http://localhost", client=("192.168.1.20", 1234)) as c:
        response = c.post(
            "/api/v1/providers/configs",
            headers={"Authorization": "Bearer " + "a" * 64},
            json={"kind": "openai", "api_key": "test-provider-secret"},
        )
        assert (
            response.status_code == 403
            and response.json()["error"]["code"] == "provider_key_requires_https"
        )
        token = app.state.pairings.create_token("Chat only")
        response = c.post(
            "/api/v1/providers/configs",
            headers={"Authorization": "Bearer " + token.token},
            json={"kind": "openai"},
        )
        assert (
            response.status_code == 403
            and response.json()["error"]["code"] == "provider_permission_required"
        )
        for method, path, body in [
            ("GET", "/api/v1/providers/configs/missing/models", None),
            ("POST", "/api/v1/providers/configs/missing/test", {}),
            (
                "POST",
                "/api/v1/providers/configs/missing/models",
                {"model_id": "fixture", "confirmed_external": True},
            ),
        ]:
            response = c.request(
                method, path, headers={"Authorization": "Bearer " + token.token}, json=body
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "provider_permission_required"


def test_fragmented_unicode_sse_is_incremental_and_bounded():
    from omnicore.providers.protocols import events

    class Fragments(httpx.AsyncByteStream):
        async def __aiter__(self):
            raw = 'data: {"text":"żółć"}\r\n\r\n'.encode()
            for byte in raw:
                yield bytes([byte])

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Fragments()))
        ) as client:
            async with client.stream("GET", "https://fixture.example") as response:
                assert [item async for item in events(response)] == [{"text": "żółć"}]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * 1_048_577)
            )
        ) as client:
            async with client.stream("GET", "https://fixture.example") as response:
                with pytest.raises(TextError, match="provider_response_invalid"):
                    _ = [item async for item in events(response)]

    asyncio.run(exercise())
