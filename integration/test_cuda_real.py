"""Hardware-only gate. Run explicitly on NVIDIA; no mocked device can pass."""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

from omnicore.text.engines import LlamaEngine
from omnicore.text.types import GenerationParameters, TextMessage


def test_real_cuda_offload_and_generation():
    executable = Path(os.environ["OMNICORE_TEST_LLAMA_CUDA_SERVER"]).resolve(strict=True)
    model = Path(os.environ["OMNICORE_TEST_GGUF"]).resolve(strict=True)
    smi = shutil.which("nvidia-smi")
    assert smi, "Hardware CUDA test requires a working NVIDIA driver"

    async def exercise():
        engine = LlamaEngine(cuda_executable=executable, executable=executable)
        try:
            assert (await engine.probe()).available
            assert "CUDA0" in engine.devices
            params = GenerationParameters(
                device="CUDA0", gpu_layers=20, max_tokens=32, context_size=512, temperature=0
            )
            await engine.load(model, params)
            # Require actual offloaded layers AND driver-reported allocation for the process.
            engine._log.seek(0)
            log = engine._log.read().decode(errors="replace")
            assert re.search(r"offloaded [1-9][0-9]*/[0-9]+ layers", log), "No GPU offload proof"
            memory = subprocess.check_output(  # noqa: S603
                [smi, "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                text=True,
                timeout=10,
            )
            assert any(
                line.split(",")[0].strip() == str(engine.process.pid)
                and int(line.split(",")[1].strip()) > 0
                for line in memory.splitlines()
            )
            chunks = [
                chunk
                async for chunk in engine.stream(
                    str(model),
                    [TextMessage(role="user", content="Write a friendly welcome.")],
                    params,
                )
            ]
            assert "".join(c.content for c in chunks).strip()
            assert engine.execution_device == "CUDA0" and engine.fallback_reason is None
        finally:
            await engine.stop()

    asyncio.run(exercise())
