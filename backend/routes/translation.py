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
from services.docx_ir import parse_docx_ir, render_docx_ir
from services.docx_security import check_docx_security
from services.excel_exporter import export_excel
from services.excel_parser import extract_segments as extract_excel_segments
from services.md_exporter import export_md
from services.md_parser import extract_segments as extract_md_segments
# PPTX translation is not supported in the current release.
from services.storage import create_stored_file_name, sanitize_download_file_name, sha256_bytes
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


def _job_json(row, *, include_debug: bool = False) -> dict:
    result = json.loads(row["result_json"]) if row["result_json"] else None
    if result and not include_debug:
        result.pop("qaProfile", None)
    return {
        "id": row["id"],
        "status": row["status"],
        "progress": row["progress"],
        "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
        "result": result,
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "finishedAt": row["finished_at"],
    }


def _pick_parser(filename: str):
    lower = filename.lower()
    if lower.endswith(".docx"):
        return "docx", None
    if lower.endswith(".xlsx"):
        return "xlsx", extract_excel_segments
    # if lower.endswith(".pptx"):                        # PPTX translation disabled
    #     return "pptx", extract_pptx_segments           # PPTX translation disabled
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "md", extract_md_segments
    raise HTTPException(status_code=400, detail="Unsupported file type")


def _parse_docx_document(content: bytes) -> dict:
    return parse_docx_ir(content)


def _batch_limits_for_file_type(file_type: str, cfg) -> tuple[int, int]:
    if file_type == "xlsx":
        return min(cfg.translation_batch_max_bytes, 3000), 50
    if file_type == "docx":
        return min(cfg.translation_batch_max_bytes, 3000), 50
    if file_type == "md":
        return min(cfg.translation_batch_max_bytes, 3000), 50
    return cfg.translation_batch_max_bytes, cfg.translation_batch_max_segments


def _build_tm_scopes(*, file_type: str, document_sha256: str | None) -> tuple[list[str], list[str]]:
    document_scope = f"document:{document_sha256}" if document_sha256 else ""
    filetype_scope = f"filetype:{file_type}"
    lookup_scopes = [scope for scope in (document_scope, filetype_scope, "global") if scope]
    write_scopes = [scope for scope in (document_scope, filetype_scope) if scope]
    return lookup_scopes, write_scopes


async def _translate_output_file_stem(
    *,
    stem: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    bearer_token: str | None,
    cfg,
    glossary_terms: list[dict],
) -> str:
    if not stem.strip():
        return "translated"

    result = await translate_segments(
        segments=[
            {
                "id": "file-name",
                "order": 0,
                "source_text": stem,
                "plain_text": stem,
                "segment_type": "label",
                "style_name": "FileName",
            }
        ],
        source_lang=source_lang,
        target_lang=target_lang,
        file_type=file_type,
        bearer_token=bearer_token,
        timeout_seconds=cfg.translation_timeout_seconds,
        glossary_terms=glossary_terms,
        glossary_max_terms=cfg.glossary_max_terms_per_request,
        glossary_max_prompt_chars=cfg.glossary_max_prompt_chars,
        batch_max_bytes=cfg.translation_batch_max_bytes,
        batch_max_segments=cfg.translation_batch_max_segments,
        bedrock_model_id=cfg.bedrock_model_id,
        bedrock_region=cfg.bedrock_region,
        bedrock_aws_profile=cfg.bedrock_aws_profile,
        qa_ai_enabled=False,
        qa_ai_model_id=cfg.qa_ai_model_id,
        qa_ai_uncertain_threshold=cfg.qa_ai_uncertain_threshold,
        qa_ai_batch_max_segments=cfg.qa_ai_batch_max_segments,
        qa_repair_enabled=False,
        qa_repair_max_attempts=0,
        qa_repair_batch_max_segments=cfg.qa_repair_batch_max_segments,
        db=None,
    )
    translated = (result["segments"][0]["draft_translation"] or "").strip()
    return translated or stem


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
        if file_type == "docx":
            docx_ir = _parse_docx_document(content)
            segments = docx_ir["segments"]
        else:
            docx_ir = None
            segments = parser(content)
    except Exception as exc:
        db.execute("UPDATE jobs SET status = 'failed', error_message = ?, finished_at = ? WHERE id = ?", (traceback.format_exc(), app.state.now(), job_id))
        return
    db.execute("UPDATE jobs SET progress = 20 WHERE id = ?", (job_id,))
    glossary_terms = glossary_matcher.load_glossary_terms(db, source_lang, target_lang)
    batch_max_bytes, batch_max_segments = _batch_limits_for_file_type(file_type, cfg)
    document_sha256 = sha256_bytes(content)
    tm_lookup_scopes, tm_write_scopes = _build_tm_scopes(file_type=file_type, document_sha256=document_sha256)
    tm_stats: dict[str, int] = {}

    # ── Progress callback: 20% base + up to 75% for translation batches ───────
    def on_batch_done(completed: int, total: int) -> None:
        if total == 0:
            return
        pct = 20 + int(75 * completed / total)
        db.execute("UPDATE jobs SET progress = ? WHERE id = ?", (pct, job_id))

    try:
        translation_result = await translate_segments(
            segments=segments,
            source_lang=source_lang,
            target_lang=target_lang,
            file_type=file_type,
            bearer_token=bearer_token,
            timeout_seconds=cfg.translation_timeout_seconds,
            glossary_terms=glossary_terms,
            glossary_max_terms=cfg.glossary_max_terms_per_request,
            glossary_max_prompt_chars=cfg.glossary_max_prompt_chars,
            batch_max_bytes=batch_max_bytes,
            batch_max_segments=batch_max_segments,
            bedrock_model_id=cfg.bedrock_model_id,
            bedrock_region=cfg.bedrock_region,
            bedrock_aws_profile=cfg.bedrock_aws_profile,
            qa_ai_enabled=cfg.qa_ai_enabled,
            qa_ai_model_id=cfg.qa_ai_model_id,
            qa_ai_uncertain_threshold=cfg.qa_ai_uncertain_threshold,
            qa_ai_batch_max_segments=cfg.qa_ai_batch_max_segments,
            qa_repair_enabled=cfg.qa_repair_enabled,
            qa_repair_max_attempts=cfg.qa_repair_max_attempts,
            qa_repair_batch_max_segments=cfg.qa_repair_batch_max_segments,
            tm_weak_ai_enabled=cfg.tm_weak_ai_enabled,
            on_batch_done=on_batch_done,
            db=db,
            tm_user_id=db.query_value("SELECT user_id FROM jobs WHERE id = ?", (job_id,)) or "system",
            now_iso=app.state.now(),
            tm_max_entries=cfg.tm_max_entries,
            tm_prune_batch_size=cfg.tm_prune_batch_size,
            tm_lookup_scopes=tm_lookup_scopes,
            tm_write_scopes=tm_write_scopes,
            tm_stats=tm_stats,
        )
    except Exception as exc:
        db.execute("UPDATE jobs SET status = 'failed', error_message = ?, finished_at = ? WHERE id = ?", (traceback.format_exc(), app.state.now(), job_id))
        return
    translated = translation_result["segments"]
    qa_profile = translation_result.get("qa_profile")
    tm_stats.update(translation_result.get("tm_stats", {}))
    now = app.state.now()
    for source, result in zip(segments, translated):
        db.execute(
            """
            INSERT INTO job_segments
            (job_id, segment_id, segment_order, source_text, draft_translation, glossary_debug_json, qa_debug_json, style_name, segment_type,
             status, qa_pass, qa_reason, from_cache, tm_quality, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, segment_id) DO UPDATE SET
                segment_order = excluded.segment_order,
                source_text = excluded.source_text,
                draft_translation = excluded.draft_translation,
                glossary_debug_json = excluded.glossary_debug_json,
                qa_debug_json = excluded.qa_debug_json,
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
                json.dumps(result.get("glossary_debug")) if (not result["qa_pass"] and result.get("glossary_debug")) else None,
                json.dumps(result.get("qa_debug")) if (not result["qa_pass"] and result.get("qa_debug")) else None,
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

    all_pass = all(r["qa_pass"] for r in translated)
    result_payload: dict = {
        "totalSegments": len(segments),
        "sourceLang": source_lang,
        "targetLang": target_lang,
        "fileType": file_type,
        "allQaPass": all_pass,
        "tmHits": tm_stats.get("hits", 0),
        "tmStored": tm_stats.get("stored", 0),
        "tmInserted": tm_stats.get("inserted", 0),
        "tmUpdated": tm_stats.get("updated", 0),
        "tmSkipped": tm_stats.get("skipped", 0),
        "tmPruned": tm_stats.get("pruned", 0),
        "qaProfile": qa_profile,
    }
    output_file_id: str | None = None

    # ── 全部 QA 通过时自动生成输出文件 ────────────────────────────────────
    if all_pass:
        try:
            payload_row = db.query_one("SELECT payload_json FROM jobs WHERE id = ?", (job_id,))
            payload = json.loads(payload_row["payload_json"])
            original_path = cfg.uploads_dir / payload["storedPath"]
            if original_path.exists():
                original_bytes = original_path.read_bytes()
                if file_type == "docx":
                    docx_ir = _parse_docx_document(original_bytes)
                    output_bytes = render_docx_ir(original_bytes, docx_ir, translated, target_lang)
                    output_ext = ".docx"
                    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                elif file_type == "xlsx":
                    output_bytes = export_excel(original_bytes, segments, translated)
                    output_ext = ".xlsx"
                    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                elif file_type == "md":
                    output_bytes = export_md(original_bytes, segments, translated)
                    output_ext = ".md"
                    mime_type = "text/markdown; charset=utf-8"
                else:
                    output_bytes = None
                if output_bytes:
                    original_file_name = payload["fileName"]
                    translated_stem = await _translate_output_file_stem(
                        stem=Path(original_file_name).stem,
                        file_type=file_type,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        bearer_token=bearer_token,
                        cfg=cfg,
                        glossary_terms=glossary_terms,
                    )
                    output_name = sanitize_download_file_name(f"{translated_stem}{output_ext}", fallback=f"translated{output_ext}")
                    output_rel = f"outputs/{create_stored_file_name(output_name)}"
                    (cfg.data_dir / output_rel).write_bytes(output_bytes)
                    file_id = str(uuid.uuid4())
                    owner_id = db.query_value("SELECT user_id FROM jobs WHERE id = ?", (job_id,)) or "system"
                    db.execute(
                        "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'translation-output', ?, ?, ?, ?, ?, ?)",
                        (file_id, owner_id, output_name, output_rel, mime_type, len(output_bytes), sha256_bytes(output_bytes), now),
                    )
                    output_file_id = file_id
                    result_payload["autoFileId"] = file_id
                    result_payload["autoFileName"] = output_name
        except Exception:
            pass  # 自动生成失败不影响任务状态

    db.execute(
        "UPDATE jobs SET status = 'succeeded', progress = 100, result_json = ?, output_file_id = COALESCE(?, output_file_id), finished_at = ? WHERE id = ?",
        (json.dumps(result_payload), output_file_id, now, job_id),
    )


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
    return {"jobs": [_job_json(row, include_debug=user.role == "super_admin") for row in rows]}


@router.get("/api/translation/jobs/{job_id}")
async def get_job(job_id: str, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    db = request.app.state.db
    row = require_job_access(db, job_id, user)
    segments = db.query_all(
        """
        SELECT segment_id, segment_order, source_text, draft_translation, glossary_debug_json, qa_debug_json, style_name, segment_type, status, qa_pass, qa_reason, from_cache, tm_quality
        FROM job_segments WHERE job_id = ? ORDER BY segment_order
        """,
        (job_id,),
    )
    return {
        "job": _job_json(row, include_debug=user.role == "super_admin"),
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
                "glossaryDebug": json.loads(item["glossary_debug_json"]) if user.role == "super_admin" and item["glossary_debug_json"] else None,
                "qaDebug": json.loads(item["qa_debug_json"]) if user.role == "super_admin" and item["qa_debug_json"] else None,
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
    source_lang = payload.get("sourceLang", "zh-CN")
    target_lang = payload.get("targetLang", "en-US")
    glossary_terms = glossary_matcher.load_glossary_terms(db, source_lang, target_lang)
    original_path = cfg.uploads_dir / payload["storedPath"]
    if not original_path.exists():
        raise HTTPException(status_code=404, detail="Original file not found")
    original_bytes = original_path.read_bytes()
    lower = file_name.lower()
    request_segments = [item.model_dump(exclude_none=True) for item in body.segments]
    if lower.endswith(".docx"):
        docx_ir = _parse_docx_document(original_bytes)
        parsed_segments = docx_ir["segments"]
        export_segments = _build_export_segments(parsed_segments, request_segments)
        output_bytes = render_docx_ir(original_bytes, docx_ir, export_segments, target_lang)
        output_ext = ".docx"
        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lower.endswith(".xlsx"):
        parsed_segments = extract_excel_segments(original_bytes)
        export_segments = _build_export_segments(parsed_segments, request_segments)
        output_bytes = export_excel(original_bytes, parsed_segments, export_segments)
        output_ext = ".xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif lower.endswith(".md") or lower.endswith(".markdown"):
        parsed_segments = extract_md_segments(original_bytes)
        export_segments = _build_export_segments(parsed_segments, request_segments)
        output_bytes = export_md(original_bytes, parsed_segments, export_segments)
        output_ext = Path(file_name).suffix or ".md"
        mime_type = "text/markdown; charset=utf-8"
    else:
        raise HTTPException(status_code=400, detail="Unsupported export type")
    translated_stem = await _translate_output_file_stem(
        stem=Path(file_name).stem,
        file_type=Path(file_name).suffix.lstrip(".").lower(),
        source_lang=source_lang,
        target_lang=target_lang,
        bearer_token=user.access_token,
        cfg=cfg,
        glossary_terms=glossary_terms,
    )
    output_name = sanitize_download_file_name(f"{translated_stem}{output_ext}", fallback=f"translated{output_ext}")
    output_rel = f"outputs/{create_stored_file_name(output_name)}"
    (cfg.data_dir / output_rel).write_bytes(output_bytes)
    file_id = str(uuid.uuid4())
    now = request.app.state.now()
    db.execute(
        "INSERT INTO files (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at) VALUES (?, ?, 'translation-output', ?, ?, ?, ?, ?, ?)",
        (file_id, user.email, output_name, output_rel, mime_type, len(output_bytes), sha256_bytes(output_bytes), now),
    )
    return {"fileId": file_id, "fileName": output_name, "downloadUrl": f"/api/files/{file_id}/download"}


# ── (Translation memory export removed) ──────────────────────────────────────
