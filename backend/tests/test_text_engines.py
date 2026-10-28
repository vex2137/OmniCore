import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from omnicore.text.engines import LlamaEngine, OllamaEngine, client_for
from omnicore.text.types import GenerationParameters, TextError, TextMessage


def test_missing_llama_and_cpu_gpu_diagnostics():
    async def exercise():
        engine = LlamaEngine(Path("/nonexistent/llama-server"))
        assert not (await engine.probe()).available
        assert await engine.models() == []
        assert await engine.capabilities("unknown") == []
        with pytest.raises(TextError, match="engine_unavailable"):
            await engine.load(Path("unused.gguf"), GenerationParameters())
        await engine.stop()

    asyncio.run(exercise())


def test_missing_ollama_is_optional():
    async def exercise():
        def unavailable(request):
            raise httpx.ConnectError("not running", request=request)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(unavailable), base_url="http://localhost"
        )
        engine = OllamaEngine(client=client)
        assert not (await engine.probe()).available
        with pytest.raises(TextError, match="engine_unavailable"):
            await engine.models()
        await engine.stop()

    asyncio.run(exercise())


def test_ollama_protocol_parameters_capabilities_stream_and_unload():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test-protocol-only"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "test-model", "size": 10}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "vision"]})
        if request.url.path == "/api/generate":
            assert json.loads(request.content)["keep_alive"] == 0
            return httpx.Response(200, json={"done": True})
        body = json.loads(request.content)
        assert body["options"]["num_predict"] == 4
        assert "gpu_layers" not in body["options"]
        return httpx.Response(
            200,
            content='{"message":{"content":"hello"}}\n'
            '{"done":true,"eval_count":2,"eval_duration":1000000000}\n',
        )

    async def exercise():
        engine = OllamaEngine(
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url="http://localhost"
            )
        )
        assert (await engine.probe()).version == "test-protocol-only"
        assert (await engine.models())[0].name == "test-model"
        assert await engine.capabilities("test-model") == ["text-generation", "vision-input"]
        chunks = [
            chunk
            async for chunk in engine.stream(
                "test-model",
                [TextMessage(role="user", content="hi")],
                GenerationParameters(max_tokens=4),
            )
        ]
        assert chunks[0].content == "hello"
        assert chunks[-1].tokens_per_second == 2
        await engine.unload("test-model")
        await engine.stop()

    asyncio.run(exercise())


def test_llama_sse_transport_and_stream_termination():
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] and body["max_tokens"] == 4
        return httpx.Response(
            200,
            content='data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"completion_tokens":1}}\n\ndata: [DONE]\n\n',
        )

    async def exercise():
        engine = LlamaEngine()
        engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://localhost"
        )
        engine.model = "test-model"
        chunks = [
            chunk
            async for chunk in engine.stream(
                "test-model",
                [TextMessage(role="user", content="hi")],
                GenerationParameters(max_tokens=4),
            )
        ]
        assert chunks[0].content == "hello"
        assert chunks[-1].output_tokens == 1
        await engine.stop()

    asyncio.run(exercise())


@pytest.mark.parametrize("engine_type", [OllamaEngine, LlamaEngine])
def test_engine_oom_is_not_silently_successful(engine_type):
    async def exercise():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, text="out of memory")
            ),
            base_url="http://localhost",
        )
        engine = OllamaEngine(client=client) if engine_type is OllamaEngine else LlamaEngine()
        if engine_type is LlamaEngine:
            engine.client, engine.model = client, "test-model"
        with pytest.raises(TextError, match="out_of_memory"):
            _ = [item async for item in engine.stream("test-model", [], GenerationParameters())]
        await engine.stop()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://user:secret@localhost", "http://localhost?q=x"]
)
def test_engine_url_validation(url):
    with pytest.raises(ValueError):
        client_for(url)


def test_owned_llama_process_load_switch_and_stop(tmp_path):
    executable = tmp_path / "trusted test server"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """
import argparse,sys
from http.server import BaseHTTPRequestHandler,HTTPServer
if '--version' in sys.argv:
 print('test-process-only 1'); sys.exit(0)
if '--list-devices' in sys.argv:
 print('Available devices:'); sys.exit(0)
p=argparse.ArgumentParser(); p.add_argument('--port',type=int)
a,_=p.parse_known_args()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
 def log_message(self,*args): pass
HTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
"""
    )
    executable.chmod(0o700)

    async def exercise():
        engine = LlamaEngine(executable, startup_timeout=5)
        assert (await engine.probe()).available
        assert engine.devices == []
        with pytest.raises(TextError, match="gpu_unavailable"):
            await engine.load(tmp_path / "unused.gguf", GenerationParameters(gpu_layers=1))
        await engine.load(tmp_path / "one.gguf", GenerationParameters())
        first = engine.process
        assert first.returncode is None
        assert await engine.capabilities(str(tmp_path / "one.gguf")) == []
        await engine.load(tmp_path / "two.gguf", GenerationParameters())
        assert first.returncode is not None
        second = engine.process
        await engine.stop()
        assert second.returncode is not None
        assert engine.process is None and engine.client is None

    asyncio.run(exercise())
