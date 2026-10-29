"""Non-secret desktop preferences, separate from backend preferences and data."""

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "omnicore" / "desktop.json"


def data_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return Path(os.environ.get("OMNICORE_DATA_DIR", str(base / "omnicore")))


def bundled_engine() -> str:
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).parent / "engines" / "llama-server"
        if path.is_file():
            return str(path)
    return os.environ.get("OMNICORE_LLAMA_SERVER", "")


@dataclass
class DesktopConfig:
    locale: str = "pl-PL"
    theme: str = "system"
    model_roots: list[str] = field(default_factory=list)
    llama_server: str = ""
    llama_cuda_server: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_enabled: bool = True
    parameters: dict = field(default_factory=dict)
    onboarding_complete: bool = False

    @classmethod
    def load(cls, path: Path | None = None):
        path = path or config_path()
        if not path.exists():
            return cls(
                llama_server=bundled_engine(),
                llama_cuda_server=os.environ.get("OMNICORE_LLAMA_CUDA_SERVER", ""),
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        obj = cls(**payload)
        if obj.locale not in {"pl-PL", "en-US"} or obj.theme not in {"system", "light", "dark"}:
            raise ValueError("Invalid desktop preferences")
        if not obj.llama_server:
            obj.llama_server = bundled_engine()
        return obj

    def save(self, path: Path | None = None):
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".tmp")
        payload = asdict(self)
        if getattr(sys, "frozen", False) and self.llama_server == bundled_engine():
            # AppImage mount/extraction paths change every launch. Persist auto-discovery.
            payload["llama_server"] = ""
        with open(temporary, "w", encoding="utf-8", opener=lambda p, f: os.open(p, f, 0o600)) as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        temporary.replace(path)
