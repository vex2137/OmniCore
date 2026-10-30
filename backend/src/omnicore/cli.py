"""Launch a single headless backend with explicit process configuration."""

import argparse
from dataclasses import replace
from pathlib import Path

import uvicorn

from omnicore.app import create_app
from omnicore.backend_lock import discover_backend
from omnicore.config import RuntimeConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniCore headless backend")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    try:
        config = RuntimeConfig.from_env()
        overrides = {key: value for key, value in vars(args).items() if value is not None}
        config = replace(config, **overrides)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        occupied = discover_backend(config.data_dir) is not None
    except OSError:
        parser.exit(74, "OmniCore: backend_lock_error; check data directory permissions.\n")
    if occupied:
        parser.exit(73, "OmniCore: backend_in_use; configure the existing server connection.\n")
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        workers=1,
        ws_max_size=config.max_body_bytes,
    )
