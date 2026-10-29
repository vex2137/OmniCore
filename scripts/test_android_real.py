"""Run Android's actual Kotlin HTTP/SSE client against isolated FastAPI + real GGUF CPU.

No emulator/phone and no inference mock. Existing weights and engine must be provided.
"""

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    model = Path(os.environ["OMNICORE_TEST_GGUF"]).resolve(strict=True)
    engine = Path(os.environ["OMNICORE_TEST_LLAMA_SERVER"]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="omnicore-android-real-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_hex(32)
        base = f"http://127.0.0.1:{port}"
        environment = {
            **os.environ,
            "OMNICORE_HOST": "127.0.0.1",
            "OMNICORE_PORT": str(port),
            "OMNICORE_DATA_DIR": directory,
            "OMNICORE_API_TOKEN": token,
            "OMNICORE_ALLOW_REMOTE": "0",
            "OMNICORE_ALLOWED_HOSTS": "localhost,127.0.0.1",
            "OMNICORE_MODEL_ROOTS": str(model.parent),
            "OMNICORE_LLAMA_SERVER": str(engine),
            "OMNICORE_OLLAMA_ENABLED": "0",
            "OMNICORE_GENERATION_TIMEOUT": "180",
            "OMNICORE_ANDROID_REAL_URL": base,
            "OMNICORE_ANDROID_REAL_TOKEN": token,
        }
        with open(Path(directory) / "backend.log", "w") as log:
            backend = subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", "from omnicore.cli import main; main()"],
                env=environment,
                cwd=ROOT,
                stdout=log,
                stderr=log,
            )
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    for _ in range(100):
                        try:
                            response = client.get(
                                f"{base}/api/v1/health",
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            if response.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if backend.poll() is not None:
                            raise RuntimeError("Isolated backend exited before readiness")
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Isolated backend readiness timed out")
                subprocess.run(  # noqa: S603
                    [
                        str(ROOT / "apps/android/gradlew"),
                        "-p",
                        str(ROOT / "apps/android"),
                        "--no-daemon",
                        "-PrealBackend=true",
                        "testDebugUnitTest",
                    ],
                    env=environment,
                    cwd=ROOT,
                    check=True,
                    timeout=600,
                )
            finally:
                backend.terminate()
                try:
                    backend.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    backend.kill()
                    backend.wait(timeout=5)
    print("Actual Kotlin client + FastAPI + GGUF CPU: PASS (not a device test)")


if __name__ == "__main__":
    main()
