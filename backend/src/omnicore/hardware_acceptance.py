"""Opt-in packaged acceptance test. Only fresh temporary data, never the user's catalog."""

import argparse
import asyncio
import json
import os
import secrets
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from omnicore.app import create_app
from omnicore.config import RuntimeConfig
from omnicore.desktop.config import bundled_engine
from omnicore.release import distribution_version
from omnicore.text import nvidia

TEXT = "/api/v1/text"


async def exercise(models, modes, *, max_tokens=512, context=4096):
    report = {
        "version": distribution_version(),
        "tests": [],
        "hardware_ready": False,
        "nvidia": await nvidia.devices(),
        "existing_data_modified": False,
    }
    with tempfile.TemporaryDirectory(prefix="omnicore-acceptance-") as directory:
        token = secrets.token_hex(32)
        engine = bundled_engine()
        config = RuntimeConfig(
            data_dir=Path(directory),
            api_token=token,
            model_roots=tuple({p.parent for p in models}),
            llama_server=Path(engine) if engine else None,
            llama_cuda_server=Path(os.environ["OMNICORE_LLAMA_CUDA_SERVER"])
            if os.environ.get("OMNICORE_LLAMA_CUDA_SERVER")
            else None,
            ollama_enabled=False,
            generation_timeout=240,
        )
        app = create_app(config)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://localhost",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                assert (
                    await client.get("/api/v1/health", headers={"Authorization": ""})
                ).status_code == 401
                diagnostics = (await client.get(TEXT + "/engines")).json()[0]
                report["engines"] = [
                    {
                        "available": c["available"],
                        "devices": c["devices"],
                        "error_code": c["error_code"],
                    }
                    for c in diagnostics.get("candidates", [])
                ]
                for path in models:
                    imported = await client.post(TEXT + "/models/import", json={"path": str(path)})
                    if imported.status_code != 201:
                        report["tests"].append(
                            {"model": path.name, "passed": False, "error": "model_import_failed"}
                        )
                        continue
                    model = imported.json()
                    for mode in modes:
                        test = {"model": path.name, "mode": mode, "passed": False}
                        report["tests"].append(test)
                        params = {
                            "device": mode,
                            "gpu_layers": 0 if mode == "cpu" else 99,
                            "context_size": context,
                            "max_tokens": max_tokens,
                            "temperature": 0,
                            "thinking": False,
                        }
                        conversation = (
                            await client.post(
                                TEXT + "/conversations",
                                json={"model_id": model["id"], "parameters": params},
                            )
                        ).json()
                        response = await client.post(
                            TEXT + f"/conversations/{conversation['id']}/generations",
                            json={
                                "content": (
                                    "Napisz trzy krótkie zdania po polsku "
                                    "o lokalnej sztucznej inteligencji."
                                ),
                                "request_key": uuid.uuid4().hex,
                            },
                        )
                        response.raise_for_status()
                        job = response.json()
                        deadline = time.monotonic() + 250
                        while job["state"] in {"queued", "running"} and time.monotonic() < deadline:
                            await asyncio.sleep(0.05)
                            job = (await client.get(TEXT + f"/generations/{job['id']}")).json()
                        for key in (
                            "state",
                            "error_code",
                            "execution_device",
                            "gpu_offloaded_layers",
                            "fallback_reason",
                            "input_tokens",
                            "output_tokens",
                            "tokens_per_second",
                            "ttft_seconds",
                            "generation_seconds",
                            "finish_reason",
                        ):
                            test[key] = job.get(key)
                        process = app.state.text.llama.process
                        memory = await nvidia.process_memory(process.pid) if process else None
                        test["allocated_vram_bytes"] = memory
                        history = (
                            await client.get(TEXT + f"/conversations/{conversation['id']}/messages")
                        ).json()
                        test["answer_sample"] = job.get("content", "")[:500]
                        test["passed"] = (
                            job["state"] == "completed"
                            and bool(job["content"].strip())
                            and "<think>" not in job["content"]
                            and "</think>" not in job["content"]
                            and history[-1]["content"] == job["content"]
                            and history[-1].get("model_name") == model["name"]
                        )
                        if mode == "cuda" or (mode == "auto" and diagnostics.get("gpu_devices")):
                            test["passed"] &= (
                                str(job.get("execution_device")).startswith("CUDA")
                                and (job.get("gpu_offloaded_layers") or 0) > 0
                                and (memory or 0) > 0
                            )
                        await client.post(TEXT + f"/models/{model['id']}/unload")
    report["passed"] = bool(report["tests"]) and all(t["passed"] for t in report["tests"])
    report["hardware_ready"] = report["passed"] and all(
        any(
            t["model"] == p.name and t.get("mode") == "cuda" and t["passed"]
            for t in report["tests"]
        )
        for p in models
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, action="append", required=True)
    parser.add_argument(
        "--modes", nargs="+", choices=("cpu", "auto", "cuda"), default=["cpu", "auto", "cuda"]
    )
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--context", type=int, default=4096)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"omnicore-hardware-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"),
    )
    args = parser.parse_args()
    try:
        report = asyncio.run(
            exercise(
                [p.resolve(strict=True) for p in args.model],
                args.modes,
                max_tokens=args.max_tokens,
                context=args.context,
            )
        )
    except Exception:
        report = {
            "passed": False,
            "hardware_ready": False,
            "error": "hardware_test_failed",
            "existing_data_modified": False,
        }
    # Never overwrite an existing report or follow a symlink; report excludes tokens/paths/logs.
    descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(
        f"Report: {args.output.name}; passed={report['passed']}; "
        f"hardware_ready={report['hardware_ready']}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
