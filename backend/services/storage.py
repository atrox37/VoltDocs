from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path


def ensure_dirs(data_dir: Path) -> None:
    for name in ("db", "uploads", "outputs", "templates", "jobs", "archives"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)


def create_stored_file_name(original_name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", original_name or "upload")
    return f"{uuid.uuid4().hex[:8]}_{safe_name}"


def sanitize_download_file_name(file_name: str, fallback: str = "output") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", (file_name or "").strip())
    cleaned = cleaned.rstrip(". ")
    return cleaned or fallback


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
