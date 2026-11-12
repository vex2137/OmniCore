"""Verify exact source and agent API in the actual extracted, frozen AppImage."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

NAME = "OmniCore-0.2.0-Agents-Beta-2-x86_64.AppImage"


def verify_tree(root, expected):
    manifest = json.loads((root / "build-manifest.json").read_text())
    if manifest["source_commit"] != expected or manifest["model_weights"] is not False:
        raise RuntimeError("Unexpected source or bundled model declaration")
    if any(root.rglob("*.gguf")):
        raise RuntimeError("GGUF must not be bundled")
    engine = root / "usr/bin/engines/llama-server"
    with engine.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != manifest["engine"]["packaged_sha256"]:
        raise RuntimeError("Packaged CPU engine checksum mismatch")
    if not (root / "usr/bin/_internal/PySide6").is_dir():
        raise RuntimeError("PySide6 is missing")
    return manifest


def request(url, token, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(  # noqa: S310 — own authenticated loopback process.
        url,
        data=body,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=3) as response:  # noqa: S310 — own loopback process only.
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimage", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = args.appimage.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="omnicore-agent-package-") as temporary:
        directory = Path(temporary)
        subprocess.run(  # noqa: S603 — AppImage just built from verified source.
            [str(image), "--appimage-extract"],
            cwd=directory,
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=90,
        )  # noqa: S603
        root = directory / "squashfs-root"
        manifest = verify_tree(root, args.expected_source)
        engine = root / "usr/bin/engines/llama-server"
        libraries = subprocess.check_output(["/usr/bin/ldd", str(engine)], text=True)  # noqa: S603
        if "not found" in libraries or any(
            s in libraries.lower() for s in ("libcuda", "libnvidia", "libcudart")
        ):
            raise RuntimeError("Missing CPU dependencies or unexpectedly bundled GPU runtime")
        version = subprocess.check_output(  # noqa: S603 — verified packaged CPU engine.
            [str(engine), "--version"], text=True, stderr=subprocess.STDOUT, timeout=30
        )  # noqa: S603
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        token = secrets.token_hex(32)
        environment = {k: v for k, v in os.environ.items() if not k.startswith("OMNICORE_")}
        environment.update(
            OMNICORE_API_TOKEN=token,
            OMNICORE_HOST="127.0.0.1",
            OMNICORE_PORT=str(port),
            OMNICORE_DATA_DIR=str(directory / "data"),
            OMNICORE_OLLAMA_ENABLED="0",
            PATH="/usr/bin:/bin",
        )
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(  # noqa: S603 — verified frozen backend, no shell.
                [str(root / "usr/bin/OmniCore"), "--backend", str(os.getpid())],
                env=environment,
                stdout=log,
                stderr=log,
            )  # noqa: S603
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 40
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Frozen backend exited during agent API smoke")
                    try:
                        request(base + "/api/v1/health", token)
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Frozen agent backend readiness timed out") from None
                        time.sleep(0.1)
                schema = request(base + "/openapi.json", token)
                for path in (
                    "/api/v1/agents/models/{model_id}/compatibility-test",
                    "/api/v1/agents/runs/{run_id}/retry",
                    "/api/v1/agents/runs/{run_id}/steps/{step_id}/approval",
                ):
                    if path not in schema["paths"]:
                        raise RuntimeError("Agents Beta 2 endpoint missing from frozen backend")
                if "retry_of" not in schema["components"]["schemas"]["AgentRequest"]["properties"]:
                    raise RuntimeError("Beta 2 request schema missing")
                conv = request(
                    base + "/api/v1/text/conversations", token, "POST", {"title": "Package smoke"}
                )
                path = base + f"/api/v1/agents/conversations/{conv['id']}"
                assert request(path + "/settings", token)["mode"] == "chat"
                changed = request(
                    path + "/settings", token, "PUT", {"mode": "agent", "max_steps": 3}
                )
                assert changed["mode"] == "agent" and changed["max_steps"] == 3
                assert request(path + "/runs", token) == []
                assert request(path + "/folders", token) == []
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        result = {
            "source_commit": args.expected_source,
            "agent_api": "PASS",
            "frozen_backend": "PASS",
            "packaged_engine": manifest["engine"],
            "engine_version": version.strip()[:500],
            "gguf_inference": "NOT TESTED",
            "kde_wayland_gpu": "NOT TESTED",
            "model_weights": False,
        }
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(
            "PASS: source, frozen agent API, PySide6, CPU engine integrity and libraries; no GGUF"
        )


if __name__ == "__main__":
    main()
