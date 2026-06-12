from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path


def _run_pandoc_sync(pandoc_path: str, args: list[str], cwd: Path, timeout_seconds: int) -> None:
    """Run pandoc synchronously using subprocess.run.

    This avoids asyncio.create_subprocess_exec which raises NotImplementedError
    on Windows when the event loop is SelectorEventLoop (used by uvicorn).
    """
    result = subprocess.run(
        [pandoc_path, *args],
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "ignore").strip()
        raise RuntimeError(f"Pandoc failed (exit {result.returncode}): {stderr}")


async def run_pandoc(pandoc_path: str, args: list[str], cwd: Path, timeout_seconds: int) -> None:
    """Async wrapper: runs pandoc in a thread pool to avoid blocking the event loop."""
    try:
        await asyncio.to_thread(_run_pandoc_sync, pandoc_path, args, cwd, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Pandoc timed out after {timeout_seconds}s") from exc
