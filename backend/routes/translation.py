from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Form, Request, UploadFile
from pydantic import BaseModel

from auth.middleware import CurrentUser, get_current_user
from services import glossary_matcher
from services.access_control import job_scope_clause, require_job_access
from services.docx_exporter import export_docx
from services.docx_parser import extract_segments as extract_docx_segments
from services.docx_security import check_docx_security
from services.excel_exporter import export_excel
from services.excel_parser import extract_segments as extract_excel_segments
from services.md_exporter import export_md
from services.md_parser import extract_segments as extract_md_segments
from services.pptx_exporter import export_pptx
from services.pptx_parser import extract_segments as extract_pptx_segments
from services.storage import create_stored_file_name, sha256_bytes
from services.translation import translate_segments


router = APIRouter()


class ExportSegmentInput(BaseModel):
    id: str | None = None
    sourceText: str | None = None
    translation: str | None = None
    draftTranslation: str | None = None
    sheet: str | None = None
    cell: str | None = None


class ExportRequest(BaseModel):
    segments: list[ExportSegmentInput]


def _normalized_source_text(item: dict) -> str:
    return (item.get("sourceText") or item.get("source_text") or "").strip()


def _build_export_segments(original_segments: list[dict], request_segments: list[dict]) -> list[dict]:
    # Prefer strict order mapping because frontend review/export preserves job segment order.
    if len(original_segments) == len(request_segments):
        combined: list[dict] = []
        for original, request in zip(original_segments, request_segments):
            merged = dict(original)
            merged.update(request)
            combined.append(merged)
        return combined

    # Fallback for length mismatch: match duplicate sourceText in order using queues.
    request_map: dict[str, list[dict]] = {}
    for request in request_segments:
        key = _normalized_source_text(request)
        request_map.setdefault(key, []).append(request)

    combined = []
    for original in original_segments:
        key = _normalized_source_text(original)
        queue = request_map.get(key, [])
        request = queue.pop(0) if queue else {}
        merged = dict(original)
        merged.update(request)
        combined.append(merged)
    return combined


def _job_json(row) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "progress": row["progress"],
        "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "finishedAt": row["finished_at"],
    }


def _pick_parser(filename: str):
    lower = filename.lower()
    if lower.endswith(".docx"):
        return "docx", extract_docx_segments
    if lower.endswith(".xlsx"):
        return "xlsx", extract_excel_segments
    if lower.endswith(".pptx"):
        return "pptx", extract_pptx_segments
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "md", extract_md_segments
    raise HTTPException(status_code=400, detail="Unsupported file type")


def _batch_limits_for_file_type(file_type: str, cfg) -> tuple[int, int]:
    if file_type == "xlsx":
        return min(cfg.translation_batch_max_bytes, 3000), min(cfg.translation_batch_max_segments, 60)
    return cfg.translation_batch_max_bytes, cfg.translation_batch_max_segments


@router.post("/api/translation/jobs", status_code=202)
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    sourceLang: str = Form(default="zh-CN"),
    targetLang: str = Form(default="en-US"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Missing file")
    cfg = request.app.state.config
    if len(content) > cfg.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large, max {cfg.max_upload_mb} MB")
    file_type, _ = _pick_parser(file.filename or "upload.docx")
    if file_type == "docx":
        security = check_docx_security(content)
        if not security["readable"]:
            raise HTTPException(status_code=400, detail=security["message"])
    db = request.app.state.db
    stored_name = create_stored_file_name(file.filename or "upload.docx")
    upload_path = cfg.uploads_dir / stored_name
    upload_path.write_bytes(content)
    now = request.app.state.now()
    file_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'translation-input', ?, ?, ?, ?, ?, ?)",
        (file_id, user.email, file.filename or "upload.docx", f"uploads/{stored_name}", file.content_type or "application/octet-stream", len(content), sha256_bytes(content), now),
    )
    job_id = str(uuid.uuid4())
    payload = {
        "sourceLang": sourceLang,
        "targetLang": targetLang,
        "fileName": file.filename or "upload.docx",
        "storedPath": stored_name,
    }
    db.execute(
        "INSERT INTO jobs (id, user_id, type, status, progress, input_file_id, payload_json, created_at) VALUES (?, ?, 'translation', 'queued', 0, ?, ?, ?)",
        (job_id, user.email, file_id, json.dumps(payload), now),
    )
    db.execute(
        "INSERT INTO glossary_audit_logs (id, term_id, action, after_json, actor, created_at) VALUES (?, NULL, 'job_created', ?, ?, ?)",
        (str(uuid.uuid4()), json.dumps({"jobId": job_id, "jobType": "translation", "sourceLang": sourceLang, "targetLang": targetLang, "fileName": file.filename}), user.email, now),
    )
    asyncio.create_task(_run_translation_job(request.app, job_id, content, file.filename or "upload.docx", sourceLang, targetLang, user.access_token))
    return {"id": job_id, "status": "queued"}


async def _run_translation_job(app, job_id: str, content: bytes, filename: str, source_lang: str, target_lang: str, bearer_token: str | None) -> None:
    db = app.state.db
    cfg = app.state.config
    db.execute("UPDATE jobs SET status = 'running', progress = 5, started_at = ? WHERE id = ?", (app.state.now(), job_id))
    file_type, parser = _pick_parser(filename)
    try:
        segments = parser(content)
    except Exception as exc:
        db.execute("UPDATE jobs SET status = 'failed', error_message = ?, finished_at = ? WHERE id = ?", (traceback.format_exc(), app.state.now(), job_id))
        return
    db.execute("UPDATE jobs SET progress = 20 WHERE id = ?", (job_id,))
    glossary_terms = glossary_matcher.load_glossary_terms(db, source_lang, target_lang)
    batch_max_bytes, batch_max_segments = _batch_limits_for_file_type(file_type, cfg)

    # ── Progress callback: 20% base + up to 75% for translation batches ───────
    def on_batch_done(completed: int, total: int) -> None:
        if total == 0:
            return
        pct = 20 + int(75 * completed / total)
        db.execute("UPDATE jobs SET progress = ? WHERE id = ?", (pct, job_id))

    try:
        translated = await translate_segments(
            segments=segments,
            source_lang=source_lang,
            target_lang=target_lang,
            bearer_token=bearer_token,
            lambda_url=cfg.translation_lambda_url,
            timeout_seconds=cfg.translation_timeout_seconds,
            glossary_terms=glossary_terms,
            glossary_max_terms=cfg.glossary_max_terms_per_request,
            glossary_max_prompt_chars=cfg.glossary_max_prompt_chars,
            batch_max_bytes=batch_max_bytes,
            batch_max_segments=batch_max_segments,
            bedrock_model_id=cfg.bedrock_model_id,
            bedrock_region=cfg.bedrock_region,
            bedrock_aws_profile=cfg.bedrock_aws_profile,
            on_batch_done=on_batch_done,
        )
    except Exception as exc:
        db.execute("UPDATE jobs SET status = 'failed', error_message = ?, finished_at = ? WHERE id = ?", (traceback.format_exc(), app.state.now(), job_id))
        return
    now = app.state.now()
    for source, result in zip(segments, translated):
        db.execute(
            """
            INSERT INTO job_segments
            (job_id, segment_id, segment_order, source_text, draft_translation, style_name, segment_type,
             status, qa_pass, qa_reason, from_cache, tm_quality, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, segment_id) DO UPDATE SET
                segment_order = excluded.segment_order,
                source_text = excluded.source_text,
                draft_translation = excluded.draft_translation,
                style_name = excluded.style_name,
                segment_type = excluded.segment_type,
                status = excluded.status,
                qa_pass = excluded.qa_pass,
                qa_reason = excluded.qa_reason,
                from_cache = excluded.from_cache,
                tm_quality = excluded.tm_quality,
                updated_at = excluded.updated_at
            """,
            (
                job_id,
                source["id"],
                source["order"],
                source["source_text"],
                result["draft_translation"],
                source.get("style_name"),
                source.get("segment_type", "paragraph"),
                "translated" if result["qa_pass"] else "qa_failed",
                int(result["qa_pass"]),
                result["qa_reason"],
                int(result["from_cache"]),
                result["tm_quality"],
                now,
            ),
        )

    # ── Write passing translations to translation memory ──────────────────────
    import hashlib
    for source, result in zip(segments, translated):
        if not result["qa_pass"] or not result["draft_translation"]:
            continue
        src_text = source["source_text"].strip()
        tgt_text = result["draft_translation"].strip()
        src_hash = hashlib.sha256(src_text.encode("utf-8")).hexdigest()
        try:
            db.execute(
                """
                INSERT INTO translation_memory
                (id, source_lang, target_lang, source_hash, source_text, target_text, quality, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_lang, target_lang, source_hash) DO UPDATE SET
                    target_text = excluded.target_text,
                    quality = excluded.quality,
                    updated_at = excluded.updated_at
                """,
                (str(uuid.uuid4()), source_lang, target_lang, src_hash, src_text, tgt_text, 90, user_id, now, now),
            )
        except Exception:
            pass  # TM write failure must not affect job status
    db.execute(
        "UPDATE jobs SET status = 'succeeded', progress = 100, result_json = ?, finished_at = ? WHERE id = ?",
        (json.dumps({"totalSegments": len(segments), "sourceLang": source_lang, "targetLang": target_lang, "fileType": file_type}), now, job_id),
    )

    # ── 全部 QA 通过时自动生成输出文件 ────────────────────────────────────
    all_pass = all(r["qa_pass"] for r in translated)
    if all_pass:
        try:
            payload_row = db.query_one("SELECT payload_json FROM jobs WHERE id = ?", (job_id,))
            payload = json.loads(payload_row["payload_json"])
            original_path = cfg.uploads_dir / payload["storedPath"]
            if original_path.exists():
                original_bytes = original_path.read_bytes()
                if file_type == "docx":
                    output_bytes = export_docx(original_bytes, segments, translated)
                    output_ext = ".docx"
                    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                elif file_type == "xlsx":
                    output_bytes = export_excel(original_bytes, segments, translated)
                    output_ext = ".xlsx"
                    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                elif file_type == "pptx":
                    output_bytes = export_pptx(original_bytes, translated)
                    output_ext = ".pptx"
                    mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                elif file_type == "md":
                    output_bytes = export_md(original_bytes, segments, translated)
                    output_ext = ".md"
                    mime_type = "text/markdown; charset=utf-8"
                else:
                    output_bytes = None
                if output_bytes:
                    orig_stem = Path(payload["fileName"]).stem
                    output_name = f"{orig_stem}_translated{output_ext}"
                    output_rel = f"outputs/{output_name}"
                    (cfg.data_dir / output_rel).write_bytes(output_bytes)
                    file_id = str(uuid.uuid4())
                    owner_id = db.query_value("SELECT user_id FROM jobs WHERE id = ?", (job_id,)) or "system"
                    db.execute(
                        "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'translation-output', ?, ?, ?, ?, ?, ?)",
                        (file_id, owner_id, output_name, output_rel, mime_type, len(output_bytes), sha256_bytes(output_bytes), now),
                    )
                    db.execute(
                        "UPDATE jobs SET result_json = ?, output_file_id = ? WHERE id = ?",
                        (json.dumps({"totalSegments": len(segments), "sourceLang": source_lang, "targetLang": target_lang, "fileType": file_type, "allQaPass": True, "autoFileId": file_id, "autoFileName": output_name}), file_id, job_id),
                    )
        except Exception:
            pass  # 自动生成失败不影响任务状态


@router.get("/api/translation/jobs")
async def list_jobs(request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    scope_sql, scope_params = job_scope_clause(user)
    rows = request.app.state.db.query_all(
        f"""
        SELECT id, status, progress, payload_json, result_json, error_message, created_at, finished_at
        FROM jobs
        WHERE type = 'translation'{scope_sql}
        ORDER BY created_at DESC
        LIMIT 50
        """,
        scope_params,
    )
    return {"jobs": [_job_json(row) for row in rows]}


@router.get("/api/translation/jobs/{job_id}")
async def get_job(job_id: str, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    db = request.app.state.db
    row = require_job_access(db, job_id, user)
    segments = db.query_all(
        """
        SELECT segment_id, segment_order, source_text, draft_translation, style_name, segment_type, status, qa_pass, qa_reason, from_cache, tm_quality
        FROM job_segments WHERE job_id = ? ORDER BY segment_order
        """,
        (job_id,),
    )
    return {
        "job": _job_json(row),
        "segments": [
            {
                "id": item["segment_id"],
                "order": item["segment_order"],
                "sourceText": item["source_text"],
                "draftTranslation": item["draft_translation"],
                "styleName": item["style_name"],
                "segmentType": item["segment_type"],
                "status": item["status"],
                "qaPass": bool(item["qa_pass"]),
                "qaReason": item["qa_reason"],
                "fromCache": bool(item["from_cache"]),
                "tmQuality": item["tm_quality"],
            }
            for item in segments
        ],
    }


@router.get("/api/translation/jobs/{job_id}/progress")
async def progress(job_id: str, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = require_job_access(request.app.state.db, job_id, user)
    return {"status": row["status"], "progress": row["progress"]}


@router.post("/api/translation/jobs/{job_id}/export")
async def export_job(job_id: str, body: ExportRequest, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    db = request.app.state.db
    cfg = request.app.state.config
    job_row = require_job_access(db, job_id, user)
    payload = json.loads(job_row["payload_json"])
    file_name = payload.get("fileName", "")
    original_path = cfg.uploads_dir / payload["storedPath"]
    if not original_path.exists():
        raise HTTPException(status_code=404, detail="Original file not found")
    original_bytes = original_path.read_bytes()
    lower = file_name.lower()
    request_segments = [item.model_dump(exclude_none=True) for item in body.segments]
    if lower.endswith(".docx"):
        parsed_segments = extract_docx_segments(original_bytes)
        export_segments = _build_export_segments(parsed_segments, request_segments)
        output_bytes = export_docx(original_bytes, parsed_segments, export_segments)
        output_ext = ".docx"
        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lower.endswith(".xlsx"):
        parsed_segments = extract_excel_segments(original_bytes)
        export_segments = _build_export_segments(parsed_segments, request_segments)
        output_bytes = export_excel(original_bytes, parsed_segments, export_segments)
        output_ext = ".xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif lower.endswith(".pptx"):
        output_bytes = export_pptx(original_bytes, export_segments)
        output_ext = ".pptx"
        mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif lower.endswith(".md") or lower.endswith(".markdown"):
        parsed_segments = extract_md_segments(original_bytes)
        export_segments = _build_export_segments(parsed_segments, request_segments)
        output_bytes = export_md(original_bytes, parsed_segments, export_segments)
        output_ext = Path(file_name).suffix or ".md"
        mime_type = "text/markdown; charset=utf-8"
    else:
        raise HTTPException(status_code=400, detail="Unsupported export type")
    orig_stem = Path(file_name).stem
    output_name = f"{orig_stem}_translated{output_ext}"
    output_rel = f"outputs/{output_name}"
    (cfg.data_dir / output_rel).write_bytes(output_bytes)
    file_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'translation-output', ?, ?, ?, ?, ?, ?)",
        (file_id, user.email, output_name, output_rel, mime_type, len(output_bytes), sha256_bytes(output_bytes), request.app.state.now()),
    )
    return {"fileId": file_id, "fileName": output_name, "downloadUrl": f"/api/files/{file_id}/download"}


# ── CSV 导出端点 ──────────────────────────────────────────────────────────────

@router.get("/api/translation/memory/export-csv")
async def export_tm_csv(request: Request, user: CurrentUser = Depends(get_current_user)):
    """导出翻译记忆库为 CSV 文件"""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    rows = request.app.state.db.query_all(
        "SELECT source_lang, target_lang, source_text, target_text, quality, created_by, created_at, updated_at "
        "FROM translation_memory ORDER BY updated_at DESC"
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["源语言", "目标语言", "原文", "译文", "质量分", "创建人", "创建时间", "更新时间"])
    for row in rows:
        writer.writerow([
            row["source_lang"], row["target_lang"],
            row["source_text"], row["target_text"],
            row["quality"], row["created_by"] or "",
            row["created_at"], row["updated_at"],
        ])
    csv_bytes = buffer.getvalue().encode("utf-8-sig")  # utf-8-sig 让 Excel 正确识别中文
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename*=UTF-8\'\'translation_memory.csv'},
    )
