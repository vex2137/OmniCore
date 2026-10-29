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
    llama_server: Path | None = None
    llama_cuda_server: Path | None = None
    llama_chat_template: str | None = None
    model_roots: tuple[Path, ...] = ()
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_enabled: bool = True
    hf_token: str | None = field(default=None, repr=False)
    generation_timeout: float = 300

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("Port must be in range 1..65535")
        if self.max_body_bytes < 1024:
            raise ValueError("Request body limit must be at least 1024 bytes")
        if not 1 <= self.generation_timeout <= 3600:
            raise ValueError("Generation timeout must be in range 1..3600 seconds")
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
            llama_server=Path(os.environ["OMNICORE_LLAMA_SERVER"])
            if os.environ.get("OMNICORE_LLAMA_SERVER")
            else None,
            llama_cuda_server=Path(os.environ["OMNICORE_LLAMA_CUDA_SERVER"])
            if os.environ.get("OMNICORE_LLAMA_CUDA_SERVER")
            else None,
            llama_chat_template=os.environ.get("OMNICORE_LLAMA_CHAT_TEMPLATE"),
            model_roots=tuple(
                Path(path)
                for path in os.environ.get("OMNICORE_MODEL_ROOTS", "").split(os.pathsep)
                if path
            ),
            ollama_url=os.environ.get("OMNICORE_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_enabled=os.environ.get("OMNICORE_OLLAMA_ENABLED", "1") != "0",
            hf_token=os.environ.get("HF_TOKEN"),
            generation_timeout=float(os.environ.get("OMNICORE_GENERATION_TIMEOUT", "300")),
            max_body_bytes=int(os.environ.get("OMNICORE_MAX_BODY_BYTES", "65536")),
        )
