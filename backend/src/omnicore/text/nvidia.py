"""NVIDIA driver diagnostics, bounded and optional. Never infer GPU use from its presence."""

import asyncio
import csv
import shutil


async def query(arguments):
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    from omnicore.text.native import native_environment

    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=native_environment(),
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 3)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode or len(output) > 65536:
            return []
        return list(csv.reader(output.decode(errors="replace").splitlines(), skipinitialspace=True))
    except (OSError, TimeoutError):
        return []


async def devices():
    rows = await query(
        [
            "--query-gpu=index,name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    result = []
    for row in rows:
        try:
            if len(row) != 5:
                continue
            result.append(
                {
                    "index": int(row[0]),
                    "name": row[1][:256],
                    "total_bytes": int(row[2]) * 1024**2,
                    "free_bytes": int(row[3]) * 1024**2,
                    "driver_version": row[4][:80],
                }
            )
        except ValueError:
            continue
    return result


async def process_memory(pid):
    rows = await query(["--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"])
    try:
        values = [int(row[1]) * 1024**2 for row in rows if len(row) == 2 and int(row[0]) == pid]
        return sum(values) if values else None
    except ValueError:
        return None
