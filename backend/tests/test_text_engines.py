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
        assert body["options"]["num_ctx"] == 8192
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
                GenerationParameters(max_tokens=4, context_size=8192),
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
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["reasoning_format"] == "deepseek"
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


@pytest.mark.parametrize("json_response", [False, True])
def test_llama_reasoning_usage_and_json_fallback(json_response):
    def handler(request):
        assert json.loads(request.content)["chat_template_kwargs"]["enable_thinking"]
        if json_response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "Answer", "reasoning_content": "Consider"},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                    "timings": {"predicted_per_second": 7.5},
                },
            )
        return httpx.Response(
            200,
            content=(
                'data: {"choices":[{"delta":{"reasoning_content":"Consider","content":null}}]}\n\n'
                'data: {"choices":[{"delta":{"content":[{"type":"text","text":"Answer"}]}},'
                '{"index":1,"delta":{"content":"ignore"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"length"}],'
                '"usage":{"prompt_tokens":12,"completion_tokens":8},'
                '"timings":{"predicted_per_second":7.5}}\n\ndata: [DONE]\n\n'
            ),
        )

    async def exercise():
        engine = LlamaEngine()
        engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://localhost"
        )
        engine.model = "test-model"
        chunks = [
            chunk
            async for chunk in engine.stream("test-model", [], GenerationParameters(thinking=True))
        ]
        assert "".join(c.content for c in chunks) == "Answer"
        assert "".join(c.reasoning_content for c in chunks) == "Consider"
        assert chunks[-1].finish_reason == "length"
        assert chunks[-1].input_tokens == 12 and chunks[-1].output_tokens == 8
        assert chunks[-1].tokens_per_second == 7.5
        await engine.stop()

    asyncio.run(exercise())


def test_context_rejection_is_not_an_empty_success():
    async def exercise():
        engine = LlamaEngine()
        engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400, text="request exceeds the available context size"
                )
            ),
            base_url="http://localhost",
        )
        engine.model = "test-model"
        with pytest.raises(TextError, match="context_limit_exceeded"):
            _ = [chunk async for chunk in engine.stream("test-model", [], GenerationParameters())]
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
import argparse,sys,json
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
if '--version' in sys.argv:
 print('test-process-only 1'); sys.exit(0)
if '--list-devices' in sys.argv:
 print('Available devices:'); sys.exit(0)
p=argparse.ArgumentParser(); p.add_argument('--port',type=int)
a,_=p.parse_known_args()
Path(__file__+".args").write_text(json.dumps(sys.argv))
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
            await engine.load(
                tmp_path / "unused.gguf", GenerationParameters(device="cuda", gpu_layers=1)
            )
        await engine.load(tmp_path / "one.gguf", GenerationParameters(context_size=4096))
        first = engine.process
        assert first.returncode is None
        arguments = json.loads(Path(str(executable) + ".args").read_text())
        assert arguments[arguments.index("--ctx-size") + 1] == "4096"
        await engine.load(tmp_path / "one.gguf", GenerationParameters(context_size=8192))
        assert first.returncode is not None
        arguments = json.loads(Path(str(executable) + ".args").read_text())
        assert arguments[arguments.index("--ctx-size") + 1] == "8192"
        first = engine.process
        assert await engine.capabilities(str(tmp_path / "one.gguf")) == []
        await engine.load(tmp_path / "two.gguf", GenerationParameters())
        assert first.returncode is not None
        second = engine.process
        await engine.stop()
        assert second.returncode is not None
        assert engine.process is None and engine.client is None

    asyncio.run(exercise())


@pytest.mark.parametrize("missing_cuda", [False, True])
def test_independent_cuda_selection_and_cpu_fallback(tmp_path, missing_cuda):
    """Real subprocess selection/cleanup with controlled HTTP; NOT GPU inference."""
    cpu, cuda = tmp_path / "cpu-server", tmp_path / "cuda-server"
    for executable, devices in [
        (cpu, "Available devices:"),
        (cuda, "CUDA init log is not a device\n  CUDA0: controlled device"),
    ]:
        executable.write_text(
            f"#!{sys.executable}\n"
            + f"DEVICES={devices!r}\n"
            + """
import argparse, json, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
if '--version' in sys.argv:
 print('protocol-test-only'); sys.exit(0)
if '--list-devices' in sys.argv:
 print(DEVICES); sys.exit(0)
p=argparse.ArgumentParser(); p.add_argument('--port', type=int)
a,_=p.parse_known_args()
Path(__file__+'.args').write_text(json.dumps(sys.argv))
if 'CUDA0' in DEVICES: print('offloaded 20/30 layers to GPU', file=sys.stderr, flush=True)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
 def log_message(self,*args): pass
HTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
"""
        )
        executable.chmod(0o700)
    if missing_cuda:
        cuda.unlink()

    async def exercise():
        engine = LlamaEngine(cpu, cuda_executable=cuda, startup_timeout=5)
        assert (await engine.probe()).available
        assert engine.devices == ([] if missing_cuda else ["CUDA0"])
        await engine.load(
            tmp_path / "model.gguf", GenerationParameters(device="auto", gpu_layers=20)
        )
        selected = cpu if missing_cuda else cuda
        args = json.loads(Path(str(selected) + ".args").read_text())
        assert args[args.index("--gpu-layers") + 1] == ("0" if missing_cuda else "20")
        assert args[args.index("--device") + 1] == ("none" if missing_cuda else "CUDA0")
        assert engine.execution_device == ("cpu" if missing_cuda else "CUDA0")
        assert engine.fallback_reason == ("gpu_unavailable" if missing_cuda else None)
        first = engine.process
        await engine.load(tmp_path / "model.gguf", GenerationParameters())
        assert first.returncode is not None or missing_cuda
        assert engine.execution_device == "cpu" and engine.fallback_reason is None
        await engine.stop()
        if missing_cuda:
            with pytest.raises(TextError, match="gpu_unavailable"):
                await engine.load(
                    tmp_path / "model.gguf", GenerationParameters(device="CUDA0", gpu_layers=20)
                )

    asyncio.run(exercise())


@pytest.fixture(autouse=True)
def isolate_native_engine_discovery(monkeypatch):
    from omnicore.text import engines

    def controlled_candidates(configured_cuda=None, configured_cpu=None):
        return [
            Path(candidate).absolute()
            for candidate in (configured_cuda, configured_cpu)
            if candidate is not None
        ]

    monkeypatch.setattr(engines, "engine_candidates", controlled_candidates)


def test_llama_fast_path_skips_probe_for_running_model(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    async def exercise():
        engine = LlamaEngine(tmp_path / "llama-server")
        model = tmp_path / "model.gguf"
        parameters = GenerationParameters(device="cpu", gpu_layers=0, context_size=4096)

        class RunningProcess:
            returncode = None
            pid = 12345

        engine.process = RunningProcess()
        engine.parameters = (str(model), 4096, 0, "cpu", str(engine.executable))
        engine._cpu_executable = engine.executable
        engine.devices = []

        probe = AsyncMock()
        monkeypatch.setattr(engine, "probe", probe)

        await engine.load(model, parameters)
        probe.assert_not_awaited()

    asyncio.run(exercise())


def test_llama_fast_path_reprobes_on_context_change_or_dead_process(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def exercise():
        engine = LlamaEngine(tmp_path / "llama-server")
        model = tmp_path / "model.gguf"

        class Process:
            returncode = None

        process = Process()
        engine.process = process
        engine._cpu_executable = engine.executable
        engine.devices = []
        engine.parameters = (str(model), 4096, 0, "cpu", str(engine.executable))

        probe = AsyncMock(return_value=SimpleNamespace(available=True))
        load_selected = AsyncMock()

        monkeypatch.setattr(engine, "probe", probe)
        monkeypatch.setattr(engine, "_load_selected", load_selected)

        await engine.load(
            model, GenerationParameters(device="cpu", gpu_layers=0, context_size=8192)
        )
        probe.assert_awaited_once()

        probe.reset_mock()
        process.returncode = 1

        await engine.load(
            model, GenerationParameters(device="cpu", gpu_layers=0, context_size=4096)
        )
        probe.assert_awaited_once()

    asyncio.run(exercise())


def _write_test_gguf(path: Path, entries: list[tuple[str, int, bytes]]) -> Path:
    import struct

    def pack_str(val: str) -> bytes:
        raw = val.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    buf = bytearray(b"GGUF")
    buf += struct.pack("<IQQ", 3, 1, len(entries))
    for key, kind, val in entries:
        buf += pack_str(key)
        buf += struct.pack("<I", kind)
        buf += val
    # One minimal F32 tensor header + alignment + 4-byte tensor payload.
    buf += pack_str("w")
    buf += struct.pack("<IQ", 1, 1)
    buf += struct.pack("<IQ", 0, 0)
    pad = (-len(buf)) % 32
    buf += b"\x00" * pad + b"\x00" * 32
    path.write_bytes(bytes(buf))
    return path


def test_auto_offload_estimation_and_gguf_layout(tmp_path):
    import struct

    from omnicore.text.offload import (
        estimate_auto_gpu_layers,
        inspect_gguf_layout,
        is_cuda_oom_log,
        next_stepdown_layers,
        parse_startup_layers,
    )

    def pack_str(val: str) -> bytes:
        raw = val.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    gguf_file = _write_test_gguf(
        tmp_path / "layout.gguf",
        [
            ("general.architecture", 8, pack_str("llama")),
            ("general.alignment", 4, struct.pack("<I", 32)),
            ("llama.block_count", 4, struct.pack("<I", 32)),
            ("llama.context_length", 4, struct.pack("<I", 32768)),
            ("llama.embedding_length", 4, struct.pack("<I", 4096)),
            ("llama.attention.head_count", 4, struct.pack("<I", 32)),
            ("llama.attention.head_count_kv", 4, struct.pack("<I", 8)),
        ],
    )
    layout = inspect_gguf_layout(gguf_file)
    assert layout is not None
    assert layout["block_count"] == 32
    assert layout["head_count_kv"] == 8

    # Small file + 32 layers fits completely inside 7 GiB free VRAM.
    layers, total, reason = estimate_auto_gpu_layers(
        gguf_file,
        context_size=8192,
        fallback_layers=99,
        free_vram_bytes=7 * 1024**3,
        layout=layout,
    )
    assert (layers, total, reason) == (33, 33, "fits_in_vram")

    # Simulate a 5.63 GiB model + 8192 context on 6.2 GiB available VRAM -> partial offload.
    large_layout = {
        "file_size_bytes": int(5.63 * 1024**3),
        "block_count": 40,
        "head_count_kv": 8,
        "key_length": 128,
        "value_length": 128,
    }
    p_layers, p_total, p_reason = estimate_auto_gpu_layers(
        gguf_file,
        context_size=8192,
        fallback_layers=99,
        free_vram_bytes=int(6.2 * 1024**3),
        layout=large_layout,
    )
    assert p_total == 41
    assert 1 <= p_layers <= 40
    assert p_reason == "vram_partial_offload"

    assert is_cuda_oom_log("cudaMalloc failed: out of memory\n")
    assert not is_cuda_oom_log("offloaded 20/32 layers to GPU\n")
    assert parse_startup_layers("load_tensors: offloaded 24/32 layers to GPU") == (24, 32)
    assert next_stepdown_layers(32, 32) < 32
    assert next_stepdown_layers(1, 32) is None


def test_llama_oom_bounded_retry_and_no_silent_cpu_fallback(tmp_path, monkeypatch):
    from omnicore.text.offload import MAX_OOM_RETRIES

    cpu, cuda = tmp_path / "cpu-server", tmp_path / "cuda-server"
    cpu_log = tmp_path / "cpu.invoked"
    attempts_log = tmp_path / "cuda.attempts.json"
    fail_until = tmp_path / "fail.count"

    cpu.write_text(
        f"#!{sys.executable}\n"
        f"CPU_LOG={str(cpu_log)!r}\n"
        + """
import sys
from pathlib import Path
if '--version' in sys.argv:
    print('cpu-test'); sys.exit(0)
if '--list-devices' in sys.argv:
    print('Available devices:'); sys.exit(0)
Path(CPU_LOG).write_text('invoked')
sys.exit(1)
"""
    )
    cpu.chmod(0o700)

    cuda.write_text(
        f"#!{sys.executable}\n"
        f"ATTEMPTS_LOG={str(attempts_log)!r}\n"
        f"FAIL_UNTIL={str(fail_until)!r}\n"
        + """
import argparse, json, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
if '--version' in sys.argv:
    print('cuda-test'); sys.exit(0)
if '--list-devices' in sys.argv:
    print('Available devices:\\n  CUDA0: RTX 4060'); sys.exit(0)
p = argparse.ArgumentParser()
p.add_argument('--port', type=int)
p.add_argument('--gpu-layers', type=int)
p.add_argument('--ctx-size', type=int)
args, _ = p.parse_known_args()
history = json.loads(Path(ATTEMPTS_LOG).read_text()) if Path(ATTEMPTS_LOG).exists() else []
history.append({'layers': args.gpu_layers, 'ctx': args.ctx_size})
Path(ATTEMPTS_LOG).write_text(json.dumps(history))
limit = int(Path(FAIL_UNTIL).read_text()) if Path(FAIL_UNTIL).exists() else 0
if len(history) <= limit:
    print('llama_model_load: n_layer = 32', file=sys.stderr, flush=True)
    print('cudaMalloc failed: out of memory', file=sys.stderr, flush=True)
    sys.exit(1)
print(f'offloaded {args.gpu_layers}/32 layers to GPU', file=sys.stderr, flush=True)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
"""
    )
    cuda.chmod(0o700)

    async def exercise():
        engine = LlamaEngine(cpu, cuda_executable=cuda, startup_timeout=5)
        monkeypatch.setattr(
            engine, "_available_vram_bytes", lambda _dev: asyncio.sleep(0, 7 * 1024**3)
        )
        assert (await engine.probe()).available
        model = tmp_path / "model.gguf"

        # Case 1: OOM twice then succeed on 3rd attempt (retry #2) keeping ctx_size=8192.
        fail_until.write_text("2")
        await engine.load(
            model,
            GenerationParameters(device="auto", gpu_offload_mode="auto", context_size=8192),
        )
        history = json.loads(attempts_log.read_text())
        assert len(history) == 3
        assert all(item["ctx"] == 8192 for item in history)
        assert history[0]["layers"] > history[1]["layers"] > history[2]["layers"] > 0
        assert engine.execution_device == "CUDA0"
        assert engine.offloaded_layers == history[-1]["layers"]
        assert engine.total_layers == 32
        assert not cpu_log.exists()
        await engine.stop()

        # Case 2: Persistent OOM stops after MAX_OOM_RETRIES without CPU fallback.
        attempts_log.unlink()
        fail_until.write_text("99")
        with pytest.raises(TextError) as exc_info:
            await engine.load(
                model,
                GenerationParameters(device="auto", gpu_offload_mode="auto", context_size=8192),
            )
        assert exc_info.value.code == "out_of_memory"
        history = json.loads(attempts_log.read_text())
        assert len(history) == 1 + MAX_OOM_RETRIES
        assert not cpu_log.exists()

        # Case 3: Max mode tries all layers first, steps down on CUDA OOM to max feasible
        # offload, and raises out_of_memory without CPU fallback when all attempts fail.
        attempts_log.unlink()
        fail_until.write_text("1")
        await engine.load(
            model,
            GenerationParameters(device="auto", gpu_offload_mode="max", context_size=8192),
        )
        history = json.loads(attempts_log.read_text())
        assert len(history) == 2
        assert history[0]["layers"] > history[1]["layers"] > 0
        assert engine.offload_mode == "max"
        assert engine.offload_reason == "oom_retry_1"
        assert engine.execution_device == "CUDA0"
        assert engine.offloaded_layers == history[-1]["layers"]
        assert not cpu_log.exists()
        await engine.stop()

        attempts_log.unlink()
        fail_until.write_text("99")
        with pytest.raises(TextError) as max_exc:
            await engine.load(
                model,
                GenerationParameters(device="auto", gpu_offload_mode="max", context_size=8192),
            )
        assert max_exc.value.code == "out_of_memory"
        assert len(json.loads(attempts_log.read_text())) == 1 + MAX_OOM_RETRIES
        assert not cpu_log.exists()

    asyncio.run(exercise())


def test_hybrid_qwen35_kv_cache_gguf_retention_and_prompt_timings(tmp_path):
    import struct

    from omnicore.text.engines import openai_chunk
    from omnicore.text.gguf import read_gguf
    from omnicore.text.offload import estimate_auto_gpu_layers, estimate_kv_bytes_per_token

    def pack_str(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack("<Q", len(b)) + b

    gguf_path = _write_test_gguf(
        tmp_path / "qwen35-hybrid.gguf",
        [
            ("general.architecture", 8, pack_str("qwen35")),
            ("general.alignment", 4, struct.pack("<I", 32)),
            ("qwen35.block_count", 4, struct.pack("<I", 33)),
            ("qwen35.full_attention_interval", 4, struct.pack("<I", 4)),
            ("qwen35.attention.head_count_kv", 4, struct.pack("<I", 4)),
            ("qwen35.attention.key_length", 4, struct.pack("<I", 256)),
            ("qwen35.attention.value_length", 4, struct.pack("<I", 256)),
            ("qwen35.context_length", 4, struct.pack("<I", 262144)),
        ],
    )
    with gguf_path.open("rb") as f:
        parsed = read_gguf(f)
    assert parsed["metadata"]["qwen35.full_attention_interval"] == 4

    layout = {
        "file_size_bytes": 5_629_111_584,
        "architecture": "qwen35",
        "block_count": 33,
        "full_attention_interval": 4,
        "head_count_kv": 4,
        "key_length": 256,
        "value_length": 256,
    }
    assert estimate_kv_bytes_per_token(layout) == 32768
    layers, total, reason = estimate_auto_gpu_layers(
        gguf_path,
        context_size=16384,
        fallback_layers=99,
        free_vram_bytes=int(6.9 * 1024**3),
        layout=layout,
    )
    assert total == 34
    assert layers >= 30
    assert reason in {"fits_in_vram", "vram_partial_offload"}

    chunk = openai_chunk(
        {
            "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
            "timings": {
                "prompt_n": 512,
                "prompt_ms": 1425.6,
                "prompt_per_second": 359.14,
                "predicted_n": 64,
                "predicted_per_second": 48.2,
            },
        }
    )
    assert chunk.prompt_processing_seconds == 1.426
    assert chunk.prompt_tokens_per_second == 359.14
    assert chunk.tokens_per_second == 48.2


def test_llama_load_unloads_previous_model_before_measuring_vram(tmp_path):
    from omnicore.schemas import BackendInfo

    async def exercise():
        model = tmp_path / "m.gguf"
        model.write_bytes(b"GGUF" + b"\x00" * 64)
        engine = LlamaEngine(tmp_path / "cpu", cuda_executable=tmp_path / "cuda")
        engine.devices = ["CUDA0"]
        engine._device_executables = {"cpu": tmp_path / "cpu", "CUDA0": tmp_path / "cuda"}
        engine._cpu_executable = tmp_path / "cpu"
        engine.candidates = []

        class LiveProc:
            returncode = None
            pid = 99999

        engine.process = LiveProc()
        engine.parameters = (str(tmp_path / "old.gguf"), 32768, 23, "CUDA0", str(tmp_path / "cuda"))
        engine.offload_mode = "auto"

        events = []

        async def fake_probe():
            return BackendInfo(id="llama.cpp", available=True, version="test")

        async def fake_unload(_name=None):
            events.append("unload")
            engine.process = None
            engine.parameters = None

        async def fake_vram(_device):
            events.append("vram")
            return 7 * 1024**3

        async def fake_load_selected(*_args, **_kwargs):
            events.append("load_selected")

        engine.probe = fake_probe
        engine.unload = fake_unload
        engine._available_vram_bytes = fake_vram
        engine._load_selected = fake_load_selected

        await engine.load(
            model, GenerationParameters(device="auto", gpu_offload_mode="auto", context_size=8192)
        )
        assert events == ["unload", "vram", "load_selected"]

    asyncio.run(exercise())


def test_llama_max_partial_offload_and_previous_model_unload(tmp_path):
    from omnicore.schemas import BackendInfo

    async def exercise():
        model = tmp_path / "m2.gguf"
        model.write_bytes(b"GGUF" + b"\x00" * 64)
        engine = LlamaEngine(tmp_path / "cpu", cuda_executable=tmp_path / "cuda")
        engine.devices = ["CUDA0"]
        engine._device_executables = {"cpu": tmp_path / "cpu", "CUDA0": tmp_path / "cuda"}
        engine._cpu_executable = tmp_path / "cpu"
        engine.candidates = []

        class LiveProc:
            returncode = None
            pid = 99998

        engine.process = LiveProc()
        engine.parameters = (str(tmp_path / "prev.gguf"), 4096, 20, "CUDA0", str(tmp_path / "cuda"))
        engine.offload_mode = "manual"
        events = []

        async def fake_probe():
            return BackendInfo(id="llama.cpp", available=True, version="test")

        async def fake_unload(_name=None):
            events.append("unload")
            engine.process = None
            engine.parameters = None

        async def fake_load_selected(path, ctx, binary, device, layers, fallback, fd=None):
            events.append(("load", device, layers, ctx))
            engine.model = str(path)
            engine.parameters = (str(path), ctx, layers, device, str(binary))
            engine.execution_device = "CUDA0"
            engine.offloaded_layers = 29
            engine.total_layers = 34
            engine.process = LiveProc()

        engine.probe = fake_probe
        engine.unload = fake_unload
        engine._load_selected = fake_load_selected

        await engine.load(
            model,
            GenerationParameters(
                device="auto", gpu_offload_mode="max", gpu_layers=0, context_size=8192
            ),
        )
        assert events[0] == "unload"
        assert events[1][1] == "CUDA0"
        assert events[1][2] == 999
        assert engine.offload_mode == "max"
        assert engine.offload_reason == "vram_partial_offload"
        assert engine.offloaded_layers == 29
        assert engine.total_layers == 34

    asyncio.run(exercise())


def test_llama_unsupported_architecture_log_and_error(tmp_path):
    from omnicore.text.offload import is_unsupported_architecture_log

    assert is_unsupported_architecture_log(
        b"error loading model architecture: unknown model architecture: 'lfm99'"
    )
    assert is_unsupported_architecture_log("unknown model architecture: 'future_arch'")
    assert not is_unsupported_architecture_log("llama_model_load: loaded all tensors")

    cpu_script = tmp_path / "llama-unsupported"
    cpu_script.write_text(
        f"#!{sys.executable}\n"
        + """
import sys
if '--version' in sys.argv:
    print('version: b5000 (test)')
    sys.exit(0)
if '--list-devices' in sys.argv:
    print('Available devices:')
    sys.exit(0)
sys.stderr.write("error loading model architecture: unknown model architecture: 'future_arch'\\n")
sys.stderr.flush()
sys.exit(1)
"""
    )
    cpu_script.chmod(0o700)
    model = tmp_path / "unsupported.gguf"
    model.write_bytes(b"GGUF" + b"\x00" * 64)

    async def exercise():
        engine = LlamaEngine(cpu_script, startup_timeout=5)
        with pytest.raises(TextError) as exc:
            await engine.load(
                model, GenerationParameters(device="cpu", gpu_layers=0, context_size=2048)
            )
        assert exc.value.code == "unsupported_architecture"
        assert exc.value.status == 422
        await engine.stop()

    asyncio.run(exercise())


def test_llama_max_mode_oom_uses_auto_estimate_upper_bound_on_second_retry(tmp_path, monkeypatch):
    import struct

    from omnicore.text import nvidia

    def pack_str(val: str) -> bytes:
        raw = val.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    model = _write_test_gguf(
        tmp_path / "contended.gguf",
        [
            ("general.architecture", 8, pack_str("llama")),
            ("general.alignment", 4, struct.pack("<I", 32)),
            ("llama.block_count", 4, struct.pack("<I", 33)),
            ("llama.context_length", 4, struct.pack("<I", 32768)),
            ("llama.embedding_length", 4, struct.pack("<I", 4096)),
            ("llama.attention.head_count", 4, struct.pack("<I", 32)),
            ("llama.attention.head_count_kv", 4, struct.pack("<I", 8)),
        ],
    )

    ngl_log = tmp_path / "ngl.json"
    cuda_script = tmp_path / "llama-cuda-oom"
    cuda_script.write_text(
        f"#!{sys.executable}\n"
        + f"""
import argparse, json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

if '--version' in sys.argv:
    print('version: b5000 (cuda)')
    sys.exit(0)
if '--list-devices' in sys.argv:
    print('Available devices:')
    print('  CUDA0: NVIDIA GeForce RTX 4060')
    sys.exit(0)

p = argparse.ArgumentParser()
p.add_argument('--port', type=int)
p.add_argument('-ngl', '--n-gpu-layers', '--gpu-layers', type=int, dest='ngl', default=0)
args, _ = p.parse_known_args()

log_path = Path({str(ngl_log)!r})
attempts = json.loads(log_path.read_text()) if log_path.exists() else []
attempts.append(args.ngl)
log_path.write_text(json.dumps(attempts))

if args.ngl > 18:
    sys.stderr.write("ggml_cuda_op_mul_mat: CUDA error: out of memory\\n")
    sys.stderr.flush()
    sys.exit(1)

sys.stderr.write(f"load_tensors: offloaded {{args.ngl}}/34 layers to GPU\\n")
sys.stderr.flush()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{{}}')
    def log_message(self, *a):
        pass

HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
"""
    )
    cuda_script.chmod(0o700)

    async def fake_query(arguments):
        if "--query-compute-apps=pid,used_memory" in arguments:
            return [["111", "4800"]]
        return [["0", "NVIDIA GeForce RTX 4060", "8188", "2400", "570.0"]]

    monkeypatch.setattr(nvidia, "query", fake_query)
    monkeypatch.setattr(
        "omnicore.text.engines.estimate_auto_gpu_layers",
        lambda *_a, **_kw: (18, 34, "vram_partial_offload"),
    )

    async def exercise():
        engine = LlamaEngine(cuda_script, cuda_executable=cuda_script, startup_timeout=5)
        await engine.load(
            model,
            GenerationParameters(
                device="auto", gpu_offload_mode="max", gpu_layers=0, context_size=8192
            ),
        )
        attempts = json.loads(ngl_log.read_text())
        assert attempts[0] >= 34
        assert attempts[-1] == 18
        assert len(attempts) <= 3
        assert engine.offload_mode == "max"
        assert engine.execution_device == "CUDA0"
        assert engine.offloaded_layers == 18
        assert engine.total_layers == 34
        await engine.stop()

    asyncio.run(exercise())


def test_available_vram_bytes_ignores_non_cuda_and_reads_cuda(tmp_path, monkeypatch):
    from omnicore.text import nvidia

    async def fake_devices():
        return [
            {"index": 0, "free_bytes": 5_000_000_000, "total_bytes": 8_000_000_000},
            {"index": 1, "free_bytes": None, "total_bytes": 10_000_000_000},
        ]

    monkeypatch.setattr(nvidia, "devices", fake_devices)

    async def exercise():
        engine = LlamaEngine(tmp_path / "cpu")
        assert await engine._available_vram_bytes("") is None
        assert await engine._available_vram_bytes("cpu") is None
        assert await engine._available_vram_bytes("Vulkan0") is None
        assert await engine._available_vram_bytes("CUDA0") == 5_000_000_000
        assert await engine._available_vram_bytes("CUDA1") == 8_500_000_000

    asyncio.run(exercise())
