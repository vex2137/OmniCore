"""Single backend per data directory; loopback discovery without credentials.

Keep the lock inode in place: unlinking it would allow two independent locks.
The descriptor is never inherited by native inference children.
"""

import fcntl
import json
import os
import stat
from pathlib import Path


class BackendInUse(RuntimeError):
    pass


class BackendLease:
    def __init__(self, directory: Path, host: str, port: int):
        self.directory, self.host, self.port = directory, host, port
        self.descriptor = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            self.directory / "backend.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                raise OSError("Invalid backend lock file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BackendInUse("A backend already uses this data directory") from None
            os.fchmod(fd, 0o600)
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps({"host": self.host, "port": self.port}).encode())
        except BaseException:
            os.close(fd)
            raise
        self.descriptor = fd
        return self

    def __exit__(self, *_):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


def discover_backend(directory: Path) -> dict | None:
    """None means unlocked; an active but invalid record must still prevent spawn."""
    try:
        fd = os.open(directory / "backend.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise OSError("Invalid backend lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
        except BlockingIOError:
            pass
        try:
            record = json.loads(os.read(fd, 4096))
            port, host = record["port"], record["host"]
            if type(port) is not int or not 1 <= port <= 65535:
                return {}
            # Never use a discovered address to send a token off this computer.
            if host not in {"localhost", "127.0.0.1", "0.0.0.0", "::", "::1"}:  # noqa: S104
                return {}
            return {"url": f"http://[::1]:{port}" if ":" in host else f"http://127.0.0.1:{port}"}
        except (ValueError, KeyError, TypeError):
            return {}
    finally:
        os.close(fd)
