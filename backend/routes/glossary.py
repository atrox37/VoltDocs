from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from io import BytesIO

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from auth.middleware import CurrentUser, get_current_user, require_min_role


router = APIRouter()

DEFAULT_SOURCE_LANG = "zh-CN"
DEFAULT_TARGET_LANG = "en-US"


class CreateTermInput(BaseModel):
    sourceLang: str = DEFAULT_SOURCE_LANG
    targetLang: str = DEFAULT_TARGET_LANG
    sourceTerm: str = Field(min_length=1)
    targetTerm: str = Field(min_length=1)
    domain: str | None = None
    context: str | None = None
    enabled: bool = True


class UpdateTermInput(BaseModel):
    targetTerm: str | None = None
    context: str | None = None
    enabled: bool | None = None


class ImportPreviewRow(BaseModel):
    sourceLang: str
    targetLang: str
    sourceTerm: str
    targetTerm: str
    context: str | None = None
    action: str
    existingId: str | None = None
    existingTargetTerm: str | None = None
    existingContext: str | None = None


class GlossaryImportCommitInput(BaseModel):
    rows: list[ImportPreviewRow]


@dataclass
class ParsedImportRow:
    source_lang: str
    target_lang: str
    source_term: str
    target_term: str
    context: str | None


HEADER_ALIASES = {
    "sourceterm": "sourceTerm",
    "source_term": "sourceTerm",
    "source term": "sourceTerm",
    "中文术语": "sourceTerm",
    "中文": "sourceTerm",
    "原文术语": "sourceTerm",
    "targetterm": "targetTerm",
    "target_term": "targetTerm",
    "target term": "targetTerm",
    "英文术语": "targetTerm",
    "英文": "targetTerm",
    "译文术语": "targetTerm",
    "context": "context",
    "上下文": "context",
    "说明": "context",
    "sourcelang": "sourceLang",
    "source_lang": "sourceLang",
    "source lang": "sourceLang",
    "源语言": "sourceLang",
    "targetlang": "targetLang",
    "target_lang": "targetLang",
    "target lang": "targetLang",
    "目标语言": "targetLang",
}


def _normalize_header(value: object) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    return HEADER_ALIASES.get(raw.lower(), raw)


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _load_csv_rows(content: bytes) -> list[dict[str, object]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, object]] = []
    for raw in reader:
        rows.append({_normalize_header(key): value for key, value in raw.items() if key})
    return rows


def _load_xlsx_rows(content: bytes) -> list[dict[str, object]]:
    workbook = openpyxl.load_workbook(BytesIO(content), data_only=True)
    sheet = workbook.active
    rows_iter = list(sheet.iter_rows(values_only=True))
    if not rows_iter:
        return []
    headers = [_normalize_header(cell) for cell in rows_iter[0]]
    rows: list[dict[str, object]] = []
    for row in rows_iter[1:]:
        if not any(cell not in (None, "") for cell in row):
            continue
        mapped: dict[str, object] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            mapped[header] = row[index] if index < len(row) else None
        rows.append(mapped)
    return rows


def _parse_import_file(filename: str, content: bytes) -> list[ParsedImportRow]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        raw_rows = _load_csv_rows(content)
    elif lower.endswith(".xlsx"):
        raw_rows = _load_xlsx_rows(content)
    else:
        raise HTTPException(status_code=400, detail="仅支持导入 .xlsx 或 .csv 术语表")

    parsed_rows: list[ParsedImportRow] = []
    for index, row in enumerate(raw_rows, start=2):
        source_term = _normalize_text(row.get("sourceTerm"))
        target_term = _normalize_text(row.get("targetTerm"))
        if not source_term and not target_term:
            continue
        if not source_term or not target_term:
            raise HTTPException(status_code=400, detail=f"第 {index} 行缺少中文术语或英文术语")

        parsed_rows.append(
            ParsedImportRow(
                source_lang=_normalize_text(row.get("sourceLang")) or DEFAULT_SOURCE_LANG,
                target_lang=_normalize_text(row.get("targetLang")) or DEFAULT_TARGET_LANG,
                source_term=source_term,
                target_term=target_term,
                context=_normalize_text(row.get("context")) or None,
            )
        )
    return parsed_rows


def _preview_import_rows(db, rows: list[ParsedImportRow]) -> list[ImportPreviewRow]:
    preview: list[ImportPreviewRow] = []
    seen: set[tuple[str, str, str]] = set()

    for row in rows:
        key = (row.source_lang, row.target_lang, row.source_term)
        if key in seen:
            continue
        seen.add(key)

        existing = db.query_one(
            """
            SELECT id, target_term, context
            FROM glossary_terms
            WHERE source_lang = ? AND target_lang = ? AND source_term = ?
            """,
            key,
        )

        if not existing:
            action = "create"
        else:
            action = "replace" if (
                existing["target_term"] != row.target_term
                or (existing["context"] or None) != row.context
            ) else "skip"

        preview.append(
            ImportPreviewRow(
                sourceLang=row.source_lang,
                targetLang=row.target_lang,
                sourceTerm=row.source_term,
                targetTerm=row.target_term,
                context=row.context,
                action=action,
                existingId=existing["id"] if existing else None,
                existingTargetTerm=existing["target_term"] if existing else None,
                existingContext=existing["context"] if existing else None,
            )
        )
    return preview


@router.get("/api/glossary")
async def list_terms(
    request: Request,
    sourceLang: str | None = DEFAULT_SOURCE_LANG,
    targetLang: str | None = DEFAULT_TARGET_LANG,
    q: str | None = None,
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    pattern = f"%{q}%" if q else None
    rows = request.app.state.db.query_all(
        """
        SELECT id, source_lang, target_lang, source_term, target_term, domain, context,
               enabled, created_at, updated_at
        FROM glossary_terms
        WHERE (? IS NULL OR source_lang = ?)
          AND (? IS NULL OR target_lang = ?)
          AND (? IS NULL OR source_term LIKE ? OR target_term LIKE ?)
        ORDER BY updated_at DESC
        LIMIT 500
        """,
        (sourceLang, sourceLang, targetLang, targetLang, pattern, pattern, pattern),
    )
    return {
        "terms": [
            {
                "id": row["id"],
                "sourceLang": row["source_lang"],
                "targetLang": row["target_lang"],
                "sourceTerm": row["source_term"],
                "targetTerm": row["target_term"],
                "domain": row["domain"],
                "context": row["context"],
                "enabled": bool(row["enabled"]),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]
    }


@router.post("/api/glossary/import/preview")
async def preview_import(
    request: Request,
    file: UploadFile = File(...),
    _: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="缺少导入文件")

    rows = _parse_import_file(file.filename or "glossary.xlsx", content)
    preview_rows = _preview_import_rows(request.app.state.db, rows)
    return {
        "summary": {
            "total": len(preview_rows),
            "create": sum(1 for row in preview_rows if row.action == "create"),
            "replace": sum(1 for row in preview_rows if row.action == "replace"),
            "skip": sum(1 for row in preview_rows if row.action == "skip"),
        },
        "rows": [row.model_dump() for row in preview_rows],
    }


@router.post("/api/glossary/import/commit")
async def commit_import(
    body: GlossaryImportCommitInput,
    request: Request,
    user: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    db = request.app.state.db
    now = request.app.state.now()
    created = 0
    replaced = 0
    skipped = 0

    for row in body.rows:
        if row.action == "skip":
            skipped += 1
            continue

        existing = db.query_one(
            """
            SELECT id, source_lang, target_lang, source_term, target_term, context
            FROM glossary_terms
            WHERE source_lang = ? AND target_lang = ? AND source_term = ?
            """,
            (row.sourceLang, row.targetLang, row.sourceTerm),
        )

        if existing:
            db.execute(
                """
                UPDATE glossary_terms SET
                    target_term = ?,
                    context = ?,
                    enabled = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (row.targetTerm, row.context, now, existing["id"]),
            )
            db.execute(
                """
                INSERT INTO glossary_audit_logs (id, term_id, action, before_json, after_json, actor, created_at)
                VALUES (?, ?, 'import_replace', ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    existing["id"],
                    json.dumps(dict(existing), ensure_ascii=False),
                    json.dumps(row.model_dump(), ensure_ascii=False),
                    user.email,
                    now,
                ),
            )
            replaced += 1
        else:
            term_id = str(uuid.uuid4())
            db.execute(
                """
                INSERT INTO glossary_terms
                (id, source_lang, target_lang, source_term, target_term, domain, context, required,
                 forbidden_terms_json, enabled, priority, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?, 1, '[]', 1, 0, ?, ?, ?)
                """,
                (
                    term_id,
                    row.sourceLang,
                    row.targetLang,
                    row.sourceTerm,
                    row.targetTerm,
                    row.context,
                    user.email,
                    now,
                    now,
                ),
            )
            db.execute(
                """
                INSERT INTO glossary_audit_logs (id, term_id, action, after_json, actor, created_at)
                VALUES (?, ?, 'import_create', ?, ?, ?)
                """,
                (str(uuid.uuid4()), term_id, json.dumps(row.model_dump(), ensure_ascii=False), user.email, now),
            )
            created += 1

    return {"ok": True, "summary": {"create": created, "replace": replaced, "skip": skipped}}


@router.post("/api/glossary/terms", status_code=201)
async def create_term(
    body: CreateTermInput,
    request: Request,
    user: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    term_id = str(uuid.uuid4())
    now = request.app.state.now()
    request.app.state.db.execute(
        """
        INSERT INTO glossary_terms
        (id, source_lang, target_lang, source_term, target_term, domain, context, required,
         forbidden_terms_json, enabled, priority, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, '[]', ?, 0, ?, ?, ?)
        """,
        (
            term_id,
            body.sourceLang,
            body.targetLang,
            body.sourceTerm.strip(),
            body.targetTerm.strip(),
            body.domain,
            body.context.strip() if body.context else None,
            int(body.enabled),
            user.email,
            now,
            now,
        ),
    )
    request.app.state.db.execute(
        """
        INSERT INTO glossary_audit_logs (id, term_id, action, after_json, actor, created_at)
        VALUES (?, ?, 'create', ?, ?, ?)
        """,
        (str(uuid.uuid4()), term_id, body.model_dump_json(), user.email, now),
    )
    return {"id": term_id}


@router.patch("/api/glossary/terms/{term_id}")
async def update_term(
    term_id: str,
    body: UpdateTermInput,
    request: Request,
    user: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    db = request.app.state.db
    before = db.query_one("SELECT * FROM glossary_terms WHERE id = ?", (term_id,))
    db.execute(
        """
        UPDATE glossary_terms SET
            target_term = COALESCE(?, target_term),
            context = COALESCE(?, context),
            enabled = COALESCE(?, enabled),
            updated_at = ?
        WHERE id = ?
        """,
        (
            body.targetTerm.strip() if body.targetTerm is not None else None,
            body.context.strip() if body.context is not None else None,
            int(body.enabled) if body.enabled is not None else None,
            request.app.state.now(),
            term_id,
        ),
    )
    db.execute(
        """
        INSERT INTO glossary_audit_logs (id, term_id, action, before_json, after_json, actor, created_at)
        VALUES (?, ?, 'update', ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            term_id,
            json.dumps(dict(before), ensure_ascii=False) if before else None,
            body.model_dump_json(exclude_none=True),
            user.email,
            request.app.state.now(),
        ),
    )
    return {"ok": True}


@router.delete("/api/glossary/terms/{term_id}")
async def delete_term(
    term_id: str,
    request: Request,
    user: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    db = request.app.state.db
    before = db.query_one("SELECT * FROM glossary_terms WHERE id = ?", (term_id,))
    db.execute("DELETE FROM glossary_terms WHERE id = ?", (term_id,))
    db.execute(
        """
        INSERT INTO glossary_audit_logs (id, term_id, action, before_json, actor, created_at)
        VALUES (?, ?, 'delete', ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            term_id,
            json.dumps(dict(before), ensure_ascii=False) if before else None,
            user.email,
            request.app.state.now(),
        ),
    )
    return {"ok": True}


@router.get("/api/glossary/audit-logs")
async def audit_logs(request: Request, _: CurrentUser = Depends(require_min_role("manager"))) -> dict:
    rows = request.app.state.db.query_all(
        """
        SELECT id, term_id, action, before_json, after_json, actor, created_at
        FROM glossary_audit_logs
        ORDER BY created_at DESC
        LIMIT 100
        """
    )
    return {
        "logs": [
            {
                "id": row["id"],
                "termId": row["term_id"],
                "action": row["action"],
                "before": row["before_json"],
                "after": row["after_json"],
                "actor": row["actor"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
    }
