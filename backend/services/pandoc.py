from __future__ import annotations

import asyncio
from pathlib import Path


async def run_pandoc(pandoc_path: str, args: list[str], cwd: Path, timeout_seconds: int) -> None:
    process = await asyncio.create_subprocess_exec(
        pandoc_path,
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        raise RuntimeError(f"Pandoc timed out after {timeout_seconds}s") from exc
    if process.returncode != 0:
        raise RuntimeError(f"Pandoc failed (exit {process.returncode}): {stderr.decode('utf-8', 'ignore').strip()}")
