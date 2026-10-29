"""Launch the actual AppImage twice. Optionally test a real, already available GGUF."""

import argparse
import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "backend/src/omnicore/distribution.json").read_text())["version"]


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
    (ROOT / "dist/appimage-test.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        "PASS: actual AppImage startup, HTTP, screenshot, shutdown, restart and persistent catalog"
    )


if __name__ == "__main__":
    main()
