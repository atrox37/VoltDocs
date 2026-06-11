from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel

from auth.middleware import CurrentUser, get_current_user, require_min_role
from services.storage import create_stored_file_name, sha256_bytes


router = APIRouter()


class UpdateTemplateInput(BaseModel):
    language: str | None = None
    tags: list[str] | None = None


@router.get("/api/templates")
async def list_templates(request: Request, _: CurrentUser = Depends(get_current_user)) -> dict:
    rows = request.app.state.db.query_all("SELECT id, file_id, file_name, language, tags_json, uploaded_by, created_at, updated_at FROM templates ORDER BY created_at DESC")
    return {
        "templates": [
            {
                "id": row["id"],
                "fileId": row["file_id"],
                "fileName": row["file_name"],
                "language": row["language"],
                "tags": row["tags_json"],
                "uploadedBy": row["uploaded_by"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]
    }


@router.post("/api/templates", status_code=201)
async def upload_template(
    request: Request,
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    tags: str | None = Form(default=""),
    user: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    content = await file.read()
    stored_name = create_stored_file_name(file.filename or "template.docx")
    path = request.app.state.config.templates_dir / stored_name
    path.write_bytes(content)
    now = request.app.state.now()
    file_id = str(uuid.uuid4())
    template_id = str(uuid.uuid4())
    request.app.state.db.execute(
        """
        INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at)
        VALUES (?, ?, 'template', ?, ?, ?, ?, ?, ?)
        """,
        (file_id, user.email, file.filename or "template.docx", f"templates/{stored_name}", file.content_type or "application/octet-stream", len(content), sha256_bytes(content), now),
    )
    tag_list = [item.strip() for item in (tags or "").split(",") if item.strip()]
    request.app.state.db.execute(
        "INSERT INTO templates (id, file_id, file_name, language, tags_json, uploaded_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (template_id, file_id, file.filename or "template.docx", language, json.dumps(tag_list), user.email, now, now),
    )
    return {"id": template_id, "fileId": file_id, "fileName": file.filename or "template.docx"}


@router.patch("/api/templates/{template_id}")
async def update_template(template_id: str, body: UpdateTemplateInput, request: Request, _: CurrentUser = Depends(require_min_role("manager"))) -> dict:
    request.app.state.db.execute(
        "UPDATE templates SET language = COALESCE(?, language), tags_json = COALESCE(?, tags_json), updated_at = ? WHERE id = ?",
        (body.language, None if body.tags is None else json.dumps(body.tags), request.app.state.now(), template_id),
    )
    return {"ok": True}


@router.delete("/api/templates/{template_id}")
async def delete_template(template_id: str, request: Request, _: CurrentUser = Depends(require_min_role("manager"))) -> dict:
    db = request.app.state.db
    row = db.query_one(
        "SELECT f.storage_path FROM templates t JOIN files f ON t.file_id = f.id WHERE t.id = ?",
        (template_id,),
    )
    db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    if row:
        path = request.app.state.config.data_dir / row["storage_path"]
        if path.exists():
            path.unlink()
    return {"ok": True}
