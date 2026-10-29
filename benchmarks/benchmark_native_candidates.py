"""Warm-cache baseline of real Python paths; never uses model weights as fixtures in Git."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from omnicore.database import Database
from omnicore.text.files import FilePolicy
from omnicore.text.gguf import read_gguf
from omnicore.text.models import ModelManager
from omnicore.text.store import TextStore


def measure(operation, repeats):
    durations = []
    for _ in range(repeats):
        before = time.perf_counter()
        operation()
        durations.append((time.perf_counter() - before) * 1000)
    return {
        "samples_ms": durations,
        "median_ms": statistics.median(durations),
        "p95_ms": sorted(durations)[max(0, int(len(durations) * 0.95 + 0.999) - 1)],
    }


async def queue_work():
    queue = asyncio.Queue(maxsize=16)

    async def worker():
        for _ in range(10000):
            await queue.get()
            queue.task_done()

    task = asyncio.create_task(worker())
    for number in range(10000):
        await queue.put(number)
    await task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    model = args.gguf.resolve(strict=True)

    def parse():
        with model.open("rb") as stream:
            read_gguf(stream)

    def checksum():
        with model.open("rb") as stream:
            hashlib.file_digest(stream, "sha256")

    with tempfile.TemporaryDirectory() as directory:
        db = Database(Path(directory) / "db")
        db.initialize()
        store = TextStore(db)
        store.initialize()
        manager = ModelManager(store, FilePolicy((model.parent,)))
        large = Path(directory) / "synthetic-4gib.gguf"
        # Keep the real metadata workload, append sparse padding; not inference weights.
        import shutil

        shutil.copyfile(model, large)
        with large.open("r+b") as stream:
            stream.truncate(4 * 1024**3)

        def parse_large():
            with large.open("rb") as stream:
                read_gguf(stream)

        def hash_large():
            with large.open("rb") as stream:
                hashlib.file_digest(stream, "sha256")

        results = {
            "gguf_metadata": measure(parse, args.repeats),
            "synthetic_4gib_metadata": measure(parse_large, args.repeats),
            "synthetic_4gib_sha256": measure(hash_large, 3),
            "catalog_reference_import": measure(lambda: manager.import_gguf(model), args.repeats),
            "sha256_full_file": measure(checksum, args.repeats),
            "queue_10000_jobs": measure(lambda: asyncio.run(queue_work()), args.repeats),
            "python_guard_bootstrap": measure(
                lambda: subprocess.run(  # noqa: S603
                    [sys.executable, "-c", "pass"], check=True
                ),
                args.repeats,
            ),
        }
    result = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "model_bytes": model.stat().st_size,
        "large_fixture": "4 GiB sparse padding appended to the same GGUF; "
        "metadata workload unchanged; not inference weights",
        "method": "warm filesystem cache; sequential repetitions; wall clock; no GPU/inference; "
        "bootstrap is an interpreter startup proxy, not process cleanup latency",
        "results": results,
        "decision": "Keep Python. GGUF reference import avoids copying weights; checksum uses "
        "OpenSSL/native hashlib; queue work is small. No measured justification "
        "for maintaining an FFI/IPC implementation or shipping a Rust runtime.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: round(value["median_ms"], 3) for key, value in results.items()}))


if __name__ == "__main__":
    main()
