from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth.middleware import CurrentUser, get_current_user
from services.access_control import job_scope_clause, require_job_access
from services.pandoc import run_pandoc
from services.storage import create_stored_file_name, sha256_bytes


router = APIRouter()


def _job_json(row) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "progress": row["progress"],
        "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "finishedAt": row["finished_at"] if "finished_at" in row.keys() else None,
    }


@router.post("/api/convert/jobs", status_code=202)
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    outputFormat: str = Form(default="docx"),
    templateId: str | None = Form(default=None),
    outputFileName: str | None = Form(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Missing file")
    cfg = request.app.state.config
    if len(content) > cfg.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large, max {cfg.max_upload_mb} MB")
    db = request.app.state.db
    stored_name = create_stored_file_name(file.filename or "upload")
    upload_path = cfg.uploads_dir / stored_name
    upload_path.write_bytes(content)
    now = request.app.state.now()
    file_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'convert-input', ?, ?, ?, ?, ?, ?)",
        (file_id, user.email, file.filename or "upload", f"uploads/{stored_name}", file.content_type or "application/octet-stream", len(content), sha256_bytes(content), now),
    )
    job_id = str(uuid.uuid4())
    payload = {
        "fileName": file.filename or "upload",
        "storedPath": stored_name,
        "outputFormat": outputFormat,
        "templateId": templateId,
        "outputFileName": outputFileName,
    }
    db.execute(
        "INSERT INTO jobs (id, user_id, type, status, progress, input_file_id, payload_json, created_at) VALUES (?, ?, 'convert', 'queued', 0, ?, ?, ?)",
        (job_id, user.email, file_id, json.dumps(payload), now),
    )
    db.execute(
        "INSERT INTO glossary_audit_logs (id, term_id, action, after_json, actor, created_at) VALUES (?, NULL, 'job_created', ?, ?, ?)",
        (str(uuid.uuid4()), json.dumps({"jobId": job_id, "jobType": "convert", "fileName": file.filename, "outputFormat": outputFormat}), user.email, now),
    )
    asyncio.create_task(_run_convert_job(request.app, job_id))
    return {"id": job_id, "status": "queued"}


def _grid_table_to_pipe_table(text: str) -> str:
    """Convert pandoc grid tables (---+---) to standard pipe tables (| col | col |).

    Grid tables look like:
      +-------+-------+
      | head1 | head2 |
      +=======+=======+
      | cell1 | cell2 |
      +-------+-------+

    Pipe tables look like:
      | head1 | head2 |
      |-------|-------|
      | cell1 | cell2 |

    Also converts simple_table (space-aligned without borders) to pipe tables.
    """
    import re

    lines = text.split("\n")
    output: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Detect start of a grid table: line starting with +--- or +=== pattern
        if re.match(r"^\+[-=+]+\+\s*$", line):
            # Collect all lines belonging to this grid table
            table_lines: list[str] = []
            while i < len(lines) and (
                re.match(r"^\+[-=+]+\+\s*$", lines[i])
                or re.match(r"^\|.*\|\s*$", lines[i])
            ):
                table_lines.append(lines[i])
                i += 1

            # Parse grid table into rows
            rows: list[list[str]] = []
            header_separator_index = -1
            for tl in table_lines:
                if re.match(r"^\+[-+]+\+\s*$", tl):
                    continue  # normal divider
                if re.match(r"^\+[=+]+\+\s*$", tl):
                    header_separator_index = len(rows)  # marks end of header
                    continue
                if re.match(r"^\|.*\|\s*$", tl):
                    cells = [c.strip() for c in tl.strip("|").split("|")]
                    rows.append(cells)

            if not rows:
                output.extend(table_lines)
                continue

            # Determine column widths for alignment
            num_cols = max(len(r) for r in rows)
            col_widths = [0] * num_cols
            for row in rows:
                for ci, cell in enumerate(row):
                    if ci < num_cols:
                        col_widths[ci] = max(col_widths[ci], len(cell))

            def format_row(row: list[str]) -> str:
                cells = []
                for ci in range(num_cols):
                    cell = row[ci] if ci < len(row) else ""
                    cells.append(f" {cell:<{col_widths[ci]}} ")
                return "|" + "|".join(cells) + "|"

            def format_sep() -> str:
                return "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"

            if header_separator_index == -1:
                header_separator_index = 1  # treat first row as header

            for ri, row in enumerate(rows):
                output.append(format_row(row))
                if ri == header_separator_index - 1:
                    output.append(format_sep())
            output.append("")
            continue

        # Detect pandoc simple_table (space-padded, no borders, with dashes separator)
        # Pattern: a line of only dashes and spaces (column separator row)
        if re.match(r"^[-\s]+$", line) and line.strip().startswith("-") and len(line.strip()) > 3:
            # Likely a simple_table separator — keep as-is, too complex to convert safely
            output.append(line)
            i += 1
            continue

        output.append(line)
        i += 1

    return "\n".join(output)


async def _run_convert_job(app, job_id: str) -> None:
    import shutil
    import tempfile

    cfg = app.state.config
    db = app.state.db
    db.execute("UPDATE jobs SET status = 'running', progress = 10, started_at = ? WHERE id = ?", (app.state.now(), job_id))
    row = db.query_one("SELECT payload_json FROM jobs WHERE id = ?", (job_id,))
    if not row:
        return
    payload = json.loads(row["payload_json"])
    input_path = (cfg.uploads_dir / payload["storedPath"]).resolve()
    extension = "md" if payload.get("outputFormat") == "md" else "docx"
    base_name = Path(payload.get("outputFileName") or payload.get("fileName") or "output").stem
    output_name = f"{base_name}.{extension}"
    output_rel = f"outputs/{job_id[:8]}_{output_name}"
    output_path = (cfg.data_dir / output_rel).resolve()

    # Only md→docx is supported. docx→md is disabled.
    if extension == "md":
        db.execute("UPDATE jobs SET status = 'failed', error_message = ?, finished_at = ? WHERE id = ?",
                   ("Word → Markdown conversion is currently disabled.", app.state.now(), job_id))
        return

    try:
        # md→docx: output file goes directly to outputs/
        args = [str(input_path), "-o", str(output_path)]
        if payload.get("templateId"):
            template = db.query_one(
                "SELECT f.storage_path FROM templates t JOIN files f ON t.file_id = f.id WHERE t.id = ?",
                (payload["templateId"],),
            )
            if template:
                args.extend(["--reference-doc", str((cfg.data_dir / template["storage_path"]).resolve())])
        await run_pandoc(cfg.pandoc_path, args, input_path.parent, cfg.pandoc_timeout_seconds)
        output_bytes = output_path.read_bytes()
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        file_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'convert-output', ?, ?, ?, ?, ?, ?)",
            (
                file_id,
                db.query_value("SELECT user_id FROM jobs WHERE id = ?", (job_id,)) or "unknown",
                output_name,
                output_rel.replace("\\", "/"),
                mime,
                len(output_bytes),
                sha256_bytes(output_bytes),
                app.state.now(),
            ),
        )
        db.execute(
            "UPDATE jobs SET status = 'succeeded', progress = 100, output_file_id = ?, result_json = ?, finished_at = ? WHERE id = ?",
            (file_id, json.dumps({"fileId": file_id, "fileName": output_name}), app.state.now(), job_id),
        )
    except Exception as exc:
        import traceback
        db.execute("UPDATE jobs SET status = 'failed', error_message = ?, finished_at = ? WHERE id = ?", (traceback.format_exc(), app.state.now(), job_id))


@router.get("/api/convert/jobs")
async def list_jobs(request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    scope_sql, scope_params = job_scope_clause(user)
    rows = request.app.state.db.query_all(
        f"""
        SELECT id, status, progress, payload_json, result_json, error_message, created_at, finished_at
        FROM jobs
        WHERE type = 'convert'{scope_sql}
        ORDER BY created_at DESC
        LIMIT 50
        """,
        scope_params,
    )
    return {"jobs": [_job_json(row) for row in rows]}


@router.get("/api/convert/jobs/{job_id}")
async def get_job(job_id: str, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = require_job_access(request.app.state.db, job_id, user)
    return _job_json(row)


@router.get("/api/convert/jobs/{job_id}/progress")
async def progress(job_id: str, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = require_job_access(request.app.state.db, job_id, user)
    return {"status": row["status"], "progress": row["progress"]}
