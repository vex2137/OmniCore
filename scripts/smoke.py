"""Exercise the installed CLI, HTTP, WebSocket and persistence across a real restart."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

from websockets.sync.client import connect


@contextmanager
def backend(data_dir: str):
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("OMNICORE_")
    }
    command = [
        sys.executable,
        "-c",
        "from omnicore.cli import main; main()",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--data-dir",
        data_dir,
    ]
    # Fixed local executable and arguments, no shell or user-supplied command.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)  # noqa: S603
        try:
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(f"Backend exited during startup: {log.read().decode()}")
                try:
                    if request(url + "/api/v1/health")["status"] == "ok":
                        break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Backend readiness timed out")
            yield url, port
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def request(url: str, payload: dict | None = None):
    # Only our loopback server is contacted. Do not send these requests to the egress proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(  # noqa: S310 — URL is our own loopback server.
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT" if data is not None else "GET",
    )
    with opener.open(req, timeout=2) as response:
        return json.load(response)


def main():
    expected = {"schema_version": 1, "locale": "pl-PL", "theme": "dark", "mode": "advanced"}
    with tempfile.TemporaryDirectory(prefix="omnicore-smoke-") as data_dir:
        with backend(data_dir) as (url, port):
            assert request(url + "/api/v1/backends") == []
            assert request(url + "/api/v1/locales/pl-PL")["messages"]["nav.chat"] == "Czat"
            with connect(f"ws://127.0.0.1:{port}/api/v1/events", proxy=None) as websocket:
                assert json.loads(websocket.recv(timeout=3))["type"] == "hello"
                websocket.send('{"type":"ping"}')
                assert json.loads(websocket.recv(timeout=3))["type"] == "pong"
                assert request(url + "/api/v1/settings", expected) == expected
                event = json.loads(websocket.recv(timeout=3))
                assert event["type"] == "settings.updated"
                assert event["settings"] == expected
        with backend(data_dir) as (url, _):
            assert request(url + "/api/v1/settings") == expected
    print(
        "PASS: CLI startup, live HTTP/WS, PL catalog, settings event and persistence after restart"
    )


if __name__ == "__main__":
    main()
