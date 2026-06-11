from __future__ import annotations

import io
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from auth.middleware import CurrentUser, get_current_user
from services.access_control import require_file_access


router = APIRouter()


@router.get("/api/files/{file_id}/download")
async def download(file_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    db = request.app.state.db
    cfg = request.app.state.config
    row = require_file_access(db, file_id, user)
    path = cfg.data_dir / row["storage_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    filename = row["original_name"]
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return FileResponse(path=path, media_type=row["mime_type"] or "application/octet-stream", filename=filename, headers={"Content-Disposition": disposition})


class BatchDownloadRequest(BaseModel):
    fileIds: list[str]
    zipName: str = "translated_files.zip"


@router.post("/api/files/batch-download")
async def batch_download(
    body: BatchDownloadRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """Pack multiple output files into a single zip and stream it back."""
    db = request.app.state.db
    cfg = request.app.state.config

    if not body.fileIds:
        raise HTTPException(status_code=400, detail="fileIds must not be empty")
    if len(body.fileIds) > 50:
        raise HTTPException(status_code=400, detail="Too many files (max 50)")

    buf = io.BytesIO()
    seen_names: dict[str, int] = {}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_id in body.fileIds:
            row = require_file_access(db, file_id, user)
            path = cfg.data_dir / row["storage_path"]
            if not path.exists():
                continue
            # Deduplicate names inside the zip
            name = row["original_name"]
            if name in seen_names:
                seen_names[name] += 1
                stem, _, ext = name.rpartition(".")
                name = f"{stem}_{seen_names[name]}.{ext}" if ext else f"{name}_{seen_names[name]}"
            else:
                seen_names[name] = 0
            zf.write(path, arcname=name)

    buf.seek(0)
    zip_name = body.zipName if body.zipName.endswith(".zip") else body.zipName + ".zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(zip_name)}"},
    )
