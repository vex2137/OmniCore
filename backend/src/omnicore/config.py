"""Explicit process configuration, separate from user preferences."""

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class RuntimeConfig:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    allow_remote: bool = False
    api_token: str | None = field(default=None, repr=False)
    allowed_origins: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    max_body_bytes: int = 65_536

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("Port must be in range 1..65535")
        if self.max_body_bytes < 1024:
            raise ValueError("Request body limit must be at least 1024 bytes")
        if not is_loopback(self.host) and not self.allow_remote:
            raise ValueError("Non-loopback binding requires OMNICORE_ALLOW_REMOTE=1")
        if self.allow_remote and (not self.api_token or len(self.api_token) < 32):
            raise ValueError("Remote access requires OMNICORE_API_TOKEN of at least 32 characters")
        if self.api_token and (not self.api_token.isascii() or not self.api_token.isalnum()):
            raise ValueError("Token must contain only ASCII letters and digits")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
        for host in self.allowed_hosts:
            if not host or any(char in host for char in "/*@?# "):
                raise ValueError("Allowed hosts must be explicit hostnames or IP addresses")

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        return cls(
            data_dir=Path(os.environ.get("OMNICORE_DATA_DIR", str(base / "omnicore"))),
            host=os.environ.get("OMNICORE_HOST", "127.0.0.1"),
            port=int(os.environ.get("OMNICORE_PORT", "8000")),
            allow_remote=os.environ.get("OMNICORE_ALLOW_REMOTE") == "1",
            api_token=os.environ.get("OMNICORE_API_TOKEN"),
            allowed_origins=tuple(
                origin.strip()
                for origin in os.environ.get("OMNICORE_ALLOWED_ORIGINS", "").split(",")
                if origin.strip()
            ),
            allowed_hosts=tuple(
                host.strip()
                for host in os.environ.get(
                    "OMNICORE_ALLOWED_HOSTS", "127.0.0.1,localhost,::1"
                ).split(",")
                if host.strip()
            ),
        )
