"""Launch the actual AppImage twice. Optionally test a real, already available GGUF."""

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "backend/src/omnicore/distribution.json").read_text())["version"]


def headless_reuse(image, environment, directory, previous):
    """Exercise the bundled server and real GUI with the same isolated database."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = secrets.token_hex(32)
    server_env = dict(environment)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        server_env.pop(name, None)
    server_env.update(
        OMNICORE_API_TOKEN=token,
        OMNICORE_HOST="127.0.0.1",
        OMNICORE_PORT=str(port),
        OMNICORE_ALLOWED_HOSTS="127.0.0.1,localhost,::1",
        OMNICORE_ALLOW_REMOTE="0",
        OMNICORE_OLLAMA_ENABLED="0",
    )
    server = subprocess.Popen(  # noqa: S603 — verified image; token is environment-only.
        [str(image), "--serve"],
        env=server_env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(trust_env=False, timeout=1) as client:
            url = f"http://127.0.0.1:{port}/api/v1/health"
            headers = {"Authorization": f"Bearer {token}"}
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                assert server.poll() is None, "Headless AppImage exited during startup"
                try:
                    if client.get(url, headers=headers).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Headless AppImage startup timeout")
            assert client.get(url).status_code == 401
            duplicate = subprocess.run(  # noqa: S603 — no shell or secrets in arguments.
                [str(image), "--serve"],
                env=server_env,
                capture_output=True,
                timeout=30,
            )
            assert duplicate.returncode == 73, "A second backend was not refused"
            gui_env = {**environment, "OMNICORE_DESKTOP_TOKEN": token}
            report = directory / "external-gui.json"
            subprocess.run(  # noqa: S603
                [str(image), "--smoke-output", str(report)],
                env=gui_env,
                check=True,
                timeout=90,
            )
            record = json.loads(report.read_text())
            assert record["ok"] and not record["owned"], "GUI did not reuse the existing server"
            assert record["history_digest"] == previous["history_digest"]
            assert server.poll() is None and client.get(url, headers=headers).status_code == 200
    finally:
        if server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=10)
                raise AssertionError("Headless server did not stop safely") from None
    print("PASS: bundled --serve without display, authentication, duplicate refusal and GUI reuse")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--appimage", type=Path, default=ROOT / f"dist/OmniCore-{VERSION}-x86_64.AppImage"
    )
    parser.add_argument("--gguf", type=Path)
    args = parser.parse_args()
    result = []
    with tempfile.TemporaryDirectory(prefix="omnicore-appimage-") as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        environment.update(
            XDG_DATA_HOME=str(directory / "data"),
            XDG_CONFIG_HOME=str(directory / "config"),
            APPIMAGE_EXTRACT_AND_RUN="1",
        )
        for name in (
            "OMNICORE_DATA_DIR",
            "OMNICORE_LLAMA_SERVER",
            "OMNICORE_DESKTOP_URL",
            "OMNICORE_DESKTOP_TOKEN",
            "PYTHONHOME",
            "PYTHONPATH",
        ):
            environment.pop(name, None)
        for index in range(2):
            report = directory / f"run-{index}.json"
            command = [
                str(args.appimage.resolve()),
                "--smoke-output",
                str(report),
                "--screenshot",
                str(ROOT / "dist/appimage-test.png"),
            ]
            if args.gguf and index == 0:
                command.extend(["--smoke-gguf", str(args.gguf.resolve())])
            # With no Python on PATH the image must still start its bundled backend/guard.
            environment["PATH"] = "/usr/bin:/bin"
            process = subprocess.Popen(command, env=environment, start_new_session=True)  # noqa: S603
            try:
                assert process.wait(timeout=220) == 0, "AppImage smoke failed"
            except BaseException:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
                raise
            record = json.loads(report.read_text())
            assert record["ok"] and record["owned"], record
            assert record["version"] == VERSION
            assert record["backend_pid"] and not Path(f"/proc/{record['backend_pid']}").exists()
            if index == 0:
                config = directory / "config/omnicore/desktop.json"
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps({"locale": "en-US", "theme": "dark"}))
            else:
                assert record["history_digest"] == result[0]["history_digest"]
                assert record["conversations"] == result[0]["conversations"]
                assert record["models"] == result[0]["models"]
                assert record["locale"] == "en-US" and record["theme"] == "dark"
            result.append(record)
        # Reproduce nested bootloaders without a GPU: the guard must remove _internal
        # even when a parent bootloader already put it into LD_LIBRARY_PATH_ORIG.
        extracted = directory / "native-check"
        extracted.mkdir()
        subprocess.run(  # noqa: S603 — the same verified AppImage, isolated extraction.
            [str(args.appimage.resolve()), "--appimage-extract"],
            cwd=extracted,
            stdout=subprocess.DEVNULL,
            check=True,
            timeout=60,
        )
        binary = extracted / "squashfs-root/usr/bin/OmniCore"
        native_env = dict(environment)
        polluted = str(binary.parent / "_internal") + ":/opt/omnicore-acceptance-cuda"
        native_env.update(LD_LIBRARY_PATH=polluted, LD_LIBRARY_PATH_ORIG=polluted)
        subprocess.run(  # noqa: S603 — fixed native shell assertion; no environment dump.
            [
                str(binary),
                "--engine-guard",
                str(os.getpid()),
                "/bin/sh",
                "-c",
                'test "$LD_LIBRARY_PATH" = /opt/omnicore-acceptance-cuda',
            ],
            env=native_env,
            check=True,
            timeout=30,
        )
        result.append(headless_reuse(args.appimage.resolve(), environment, directory, result[-1]))
    (ROOT / "dist/appimage-test.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        "PASS: actual AppImage startup, HTTP, screenshot, shutdown, restart and persistent catalog"
    )


if __name__ == "__main__":
    main()
