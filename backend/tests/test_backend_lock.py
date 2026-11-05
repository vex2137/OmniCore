import json
import os
import socket
import stat
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.backend_lock import BackendInUse, BackendLease, discover_backend


def test_lock_excludes_second_process_without_exposing_credentials(tmp_path):
    with BackendLease(tmp_path, "127.0.0.1", 8765):
        assert discover_backend(tmp_path) == {"url": "http://127.0.0.1:8765"}
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-c",
                "from omnicore.cli import main; main()",
                "--data-dir",
                str(tmp_path),
            ],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 73 and b"backend_in_use" in result.stderr
        record = json.loads((tmp_path / "backend.lock").read_text())
        assert record == {"host": "127.0.0.1", "port": 8765}
        assert stat.S_IMODE((tmp_path / "backend.lock").stat().st_mode) == 0o600
    assert discover_backend(tmp_path) is None
    with BackendLease(tmp_path, "::1", 8766):
        assert discover_backend(tmp_path) == {"url": "http://[::1]:8766"}


def test_asgi_lifespan_cannot_start_a_second_scheduler(config):
    with TestClient(create_app(config), base_url="http://localhost"):
        with (
            pytest.raises(BackendInUse),
            TestClient(create_app(config), base_url="http://localhost"),
        ):
            pass
    with TestClient(create_app(config), base_url="http://localhost") as client:
        assert client.get("/api/v1/health").status_code == 200


def test_stale_metadata_never_redirects_a_client_and_active_remote_address_is_rejected(tmp_path):
    with BackendLease(tmp_path, "external.invalid", 8000):
        assert discover_backend(tmp_path) == {}
    assert discover_backend(tmp_path) is None


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_non_regular_locks_are_rejected_without_blocking_or_modifying_target(tmp_path, kind):
    path = tmp_path / "backend.lock"
    target = tmp_path / "untouched"
    target.write_text("preserve")
    if kind == "symlink":
        path.symlink_to(target)
    else:
        os.mkfifo(path)
    with pytest.raises(OSError):
        discover_backend(tmp_path)
    with pytest.raises(OSError):
        with BackendLease(tmp_path, "127.0.0.1", 8000):
            pass
    assert target.read_text() == "preserve"


def test_busy_port_releases_the_data_lease_after_startup_failure(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-c",
                "from omnicore.cli import main; main()",
                "--data-dir",
                str(tmp_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env={**os.environ, "OMNICORE_OLLAMA_ENABLED": "0"},
            capture_output=True,
            timeout=15,
        )
    assert result.returncode != 0
    assert discover_backend(tmp_path) is None
