"""Discovery/control tests only; GPU inference requires integration/test_cuda_real.py."""

import asyncio
import sys
from pathlib import Path

import pytest

from omnicore.text.engines import LlamaEngine
from omnicore.text.native import engine_candidates, native_environment
from omnicore.text.types import GenerationParameters, TextError


def controlled_server(path, *, gpu=False, offload=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\nGPU={gpu!r}\nOFFLOAD={offload!r}\n"
        + """
import sys, argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
if '--version' in sys.argv:
 print('controlled protocol only'); sys.exit(0)
if '--list-devices' in sys.argv:
 print('CUDA initialization is not a device')
 if GPU: print('  CUDA0: NVIDIA test device (8192 MiB)')
 sys.exit(0)
p=argparse.ArgumentParser(); p.add_argument('--port', type=int)
a,_=p.parse_known_args()
if OFFLOAD: print('load_tensors: offloaded 20/30 layers to GPU', file=sys.stderr, flush=True)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
 def log_message(self,*args): pass
HTTPServer(('127.0.0.1',a.port), Handler).serve_forever()
"""
    )
    path.chmod(0o700)
    return path


def test_bounded_discovery_includes_user_llama_build_without_scanning(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    cpu = controlled_server(tmp_path / "cpu")
    cuda = controlled_server(tmp_path / "llama.cpp/build/bin/llama-server", gpu=True, offload=True)
    hidden = controlled_server(tmp_path / "arbitrary-model-directory/llama-server", gpu=True)
    assert hidden not in engine_candidates(None, cpu)
    assert len(engine_candidates(None, cpu)) <= 10

    async def exercise():
        engine = LlamaEngine(cpu, startup_timeout=5)
        try:
            assert (await engine.probe()).available
            assert engine.devices == ["CUDA0"]
            assert engine._device_executables["CUDA0"] == cuda
            with pytest.raises(TextError, match="gpu_layers_required"):
                await engine.load(tmp_path / "fixture.gguf", GenerationParameters(device="cuda"))
            for device in ["auto", "cuda", "cpu", "auto"]:
                await engine.load(
                    tmp_path / "fixture.gguf", GenerationParameters(device=device, gpu_layers=20)
                )
                assert engine.execution_device == ("cpu" if device == "cpu" else "CUDA0")
                assert engine.offloaded_layers == (0 if device == "cpu" else 20)
        finally:
            await engine.stop()

    asyncio.run(exercise())


def test_no_offload_is_never_reported_as_cuda_and_auto_falls_back(tmp_path):
    cpu = controlled_server(tmp_path / "cpu")
    cuda = controlled_server(tmp_path / "cuda", gpu=True)

    async def exercise():
        engine = LlamaEngine(cpu, cuda_executable=cuda, startup_timeout=5)
        try:
            with pytest.raises(TextError, match="gpu_offload_unverified"):
                await engine.load(
                    tmp_path / "fixture.gguf", GenerationParameters(device="cuda", gpu_layers=20)
                )
            assert engine.process is None
            await engine.load(
                tmp_path / "fixture.gguf", GenerationParameters(device="auto", gpu_layers=20)
            )
            assert engine.execution_device == "cpu"
            assert engine.fallback_reason == "gpu_offload_unverified"
            assert engine.offloaded_layers == 0
        finally:
            await engine.stop()

    asyncio.run(exercise())


@pytest.mark.parametrize("original", [None, "/usr/local/cuda/lib64"])
def test_external_engine_restores_original_library_path_in_appimage(original):
    environment = {"LD_LIBRARY_PATH": "/application/_internal", "PATH": "/usr/bin"}
    if original:
        environment["LD_LIBRARY_PATH_ORIG"] = original
    sanitized = native_environment(environment, frozen=True)
    assert sanitized.get("LD_LIBRARY_PATH") == original
    assert sanitized["PATH"] == "/usr/bin"
    assert environment["LD_LIBRARY_PATH"] == "/application/_internal"


def test_nvidia_vram_and_process_memory_are_reported_from_driver(monkeypatch):
    from omnicore.text import nvidia

    async def query(arguments):
        if "--query-compute-apps=pid,used_memory" in arguments:
            return [["42", "123"], ["43", "99"]]
        return [["0", "NVIDIA GeForce RTX 4060", "8192", "7000", "615.78.08"], ["bad"]]

    monkeypatch.setattr(nvidia, "query", query)

    async def exercise():
        info = await nvidia.devices()
        assert info[0]["total_bytes"] == 8192 * 1024**2
        assert info[0]["free_bytes"] == 7000 * 1024**2
        assert await nvidia.process_memory(42) == 123 * 1024**2
        assert await nvidia.process_memory(999) is None

    asyncio.run(exercise())
