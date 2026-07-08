from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request

from auth.middleware import CurrentUser, require_super_admin


router = APIRouter()


def _parse_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_date_start(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value}T00:00:00Z"


def _normalize_date_end(value: str | None) -> str | None:
    if not value:
        return None
    next_day = date.fromisoformat(value) + timedelta(days=1)
    return f"{next_day.isoformat()}T00:00:00Z"


def _job_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    file_type: str | None,
    source_lang: str | None,
    target_lang: str | None,
    user_email: str | None,
    alias: str = "j",
) -> tuple[str, list[object]]:
    clauses = [f"{alias}.type = 'translation'"]
    params: list[object] = []

    start = _normalize_date_start(date_from)
    end = _normalize_date_end(date_to)
    if start:
        clauses.append(f"{alias}.created_at >= ?")
        params.append(start)
    if end:
        clauses.append(f"{alias}.created_at < ?")
        params.append(end)
    if file_type:
        clauses.append(f"json_extract({alias}.result_json, '$.fileType') = ?")
        params.append(file_type)
    if source_lang:
        clauses.append(f"json_extract({alias}.payload_json, '$.sourceLang') = ?")
        params.append(source_lang)
    if target_lang:
        clauses.append(f"json_extract({alias}.payload_json, '$.targetLang') = ?")
        params.append(target_lang)
    if user_email:
        clauses.append(f"{alias}.user_id = ?")
        params.append(user_email)

    return " AND ".join(clauses), params


def _tm_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    file_type: str | None,
    source_lang: str | None,
    target_lang: str | None,
    user_email: str | None,
    alias: str = "tm",
) -> tuple[str, list[object]]:
    clauses = ["1 = 1"]
    params: list[object] = []

    start = _normalize_date_start(date_from)
    end = _normalize_date_end(date_to)
    if start:
        clauses.append(f"{alias}.created_at >= ?")
        params.append(start)
    if end:
        clauses.append(f"{alias}.created_at < ?")
        params.append(end)
    if file_type:
        clauses.append(f"{alias}.scope = ?")
        params.append(f"filetype:{file_type}")
    if source_lang:
        clauses.append(f"{alias}.source_lang = ?")
        params.append(source_lang)
    if target_lang:
        clauses.append(f"{alias}.target_lang = ?")
        params.append(target_lang)
    if user_email:
        clauses.append(f"{alias}.created_by = ?")
        params.append(user_email)

    return " AND ".join(clauses), params


def _scope_family(scope: str) -> str:
    if scope.startswith("document:"):
        return "document"
    if scope.startswith("filetype:"):
        return "filetype"
    return "global"


def _build_filter_options(db) -> dict:
    rows = db.query_all(
        """
        SELECT
            user_id,
            json_extract(payload_json, '$.sourceLang') AS source_lang,
            json_extract(payload_json, '$.targetLang') AS target_lang,
            json_extract(result_json, '$.fileType') AS file_type
        FROM jobs
        WHERE type = 'translation'
        """
    )
    users = sorted({row["user_id"] for row in rows if row["user_id"]})
    file_types = sorted({row["file_type"] for row in rows if row["file_type"]})
    language_pairs = sorted(
        {
            (row["source_lang"], row["target_lang"])
            for row in rows
            if row["source_lang"] and row["target_lang"]
        }
    )
    return {
        "users": users,
        "fileTypes": file_types,
        "languagePairs": [
            {"sourceLang": source, "targetLang": target}
            for source, target in language_pairs
        ],
    }


@router.get("/api/admin/quality/summary")
async def quality_summary(
    request: Request,
    _: CurrentUser = Depends(require_super_admin),
    dateFrom: str | None = Query(default=None),
    dateTo: str | None = Query(default=None),
    fileType: str | None = Query(default=None),
    sourceLang: str | None = Query(default=None),
    targetLang: str | None = Query(default=None),
    userEmail: str | None = Query(default=None),
) -> dict:
    db = request.app.state.db
    job_where, job_params = _job_filters(
        date_from=dateFrom,
        date_to=dateTo,
        file_type=fileType,
        source_lang=sourceLang,
        target_lang=targetLang,
        user_email=userEmail,
    )
    tm_where, tm_params = _tm_filters(
        date_from=dateFrom,
        date_to=dateTo,
        file_type=fileType,
        source_lang=sourceLang,
        target_lang=targetLang,
        user_email=userEmail,
    )

    job_total = int(db.query_value(f"SELECT COUNT(*) FROM jobs j WHERE {job_where}", tuple(job_params)) or 0)
    segment_total = int(
        db.query_value(
            f"""
            SELECT COUNT(*)
            FROM job_segments js
            JOIN jobs j ON j.id = js.job_id
            WHERE {job_where}
            """,
            tuple(job_params),
        )
        or 0
    )
    qa_failed = int(
        db.query_value(
            f"""
            SELECT COUNT(*)
            FROM job_segments js
            JOIN jobs j ON j.id = js.job_id
            WHERE {job_where} AND js.qa_pass = 0
            """,
            tuple(job_params),
        )
        or 0
    )
    tm_rows = db.query_all(
        f"""
        SELECT result_json
        FROM jobs j
        WHERE {job_where}
        """,
        tuple(job_params),
    )
    tm_ops = Counter()
    for row in tm_rows:
        result = _parse_json(row["result_json"])
        tm_ops["hits"] += int(result.get("tmHits", 0) or 0)
        tm_ops["inserted"] += int(result.get("tmInserted", 0) or 0)
        tm_ops["updated"] += int(result.get("tmUpdated", 0) or 0)
        tm_ops["skipped"] += int(result.get("tmSkipped", 0) or 0)
        tm_ops["pruned"] += int(result.get("tmPruned", 0) or 0)

    tm_total = int(db.query_value(f"SELECT COUNT(*) FROM translation_memory tm WHERE {tm_where}", tuple(tm_params)) or 0)
    tier_rows = db.query_all(
        f"""
        SELECT quality_tier, COUNT(*) AS count
        FROM translation_memory tm
        WHERE {tm_where}
        GROUP BY quality_tier
        ORDER BY count DESC
        """,
        tuple(tm_params),
    )
    tier_counts = {row["quality_tier"]: int(row["count"]) for row in tier_rows}

    return {
        "filters": _build_filter_options(db),
        "summary": {
            "jobTotal": job_total,
            "segmentTotal": segment_total,
            "qaFailedSegments": qa_failed,
            "qaFailureRate": round((qa_failed / segment_total) * 100, 2) if segment_total else 0.0,
            "tmHits": tm_ops["hits"],
            "tmInserted": tm_ops["inserted"],
            "tmUpdated": tm_ops["updated"],
            "tmSkipped": tm_ops["skipped"],
            "tmPruned": tm_ops["pruned"],
            "tmRecordTotal": tm_total,
            "tmRiskyTotal": tier_counts.get("repaired_or_risky", 0),
            "tmHumanConfirmedTotal": tier_counts.get("human_confirmed", 0),
        },
    }


@router.get("/api/admin/quality/qa")
async def quality_qa(
    request: Request,
    _: CurrentUser = Depends(require_super_admin),
    dateFrom: str | None = Query(default=None),
    dateTo: str | None = Query(default=None),
    fileType: str | None = Query(default=None),
    sourceLang: str | None = Query(default=None),
    targetLang: str | None = Query(default=None),
    userEmail: str | None = Query(default=None),
) -> dict:
    db = request.app.state.db
    job_where, job_params = _job_filters(
        date_from=dateFrom,
        date_to=dateTo,
        file_type=fileType,
        source_lang=sourceLang,
        target_lang=targetLang,
        user_email=userEmail,
    )
    rows = db.query_all(
        f"""
        SELECT
            js.qa_reason,
            js.qa_debug_json,
            js.segment_type,
            j.user_id,
            substr(j.created_at, 1, 10) AS created_day,
            json_extract(j.result_json, '$.fileType') AS file_type
        FROM job_segments js
        JOIN jobs j ON j.id = js.job_id
        WHERE {job_where} AND js.qa_pass = 0
        """,
        tuple(job_params),
    )

    failure_types = Counter()
    rules = Counter()
    file_types = Counter()
    users = Counter()
    trend = defaultdict(int)

    for row in rows:
        qa_debug = _parse_json(row["qa_debug_json"])
        failure_type = qa_debug.get("finalFailureType") or "other"
        rule_name = qa_debug.get("finalRuleName") or "other"
        failure_types[str(failure_type)] += 1
        rules[str(rule_name)] += 1
        file_types[str(row["file_type"] or "unknown")] += 1
        users[str(row["user_id"] or "unknown")] += 1
        trend[str(row["created_day"] or "unknown")] += 1

    return {
        "failureTypes": [{"key": key, "count": count} for key, count in failure_types.most_common()],
        "rules": [{"key": key, "count": count} for key, count in rules.most_common()],
        "fileTypes": [{"key": key, "count": count} for key, count in file_types.most_common()],
        "users": [{"key": key, "count": count} for key, count in users.most_common()],
        "trend": [{"date": key, "count": trend[key]} for key in sorted(trend)],
    }


@router.get("/api/admin/quality/tm")
async def quality_tm(
    request: Request,
    _: CurrentUser = Depends(require_super_admin),
    dateFrom: str | None = Query(default=None),
    dateTo: str | None = Query(default=None),
    fileType: str | None = Query(default=None),
    sourceLang: str | None = Query(default=None),
    targetLang: str | None = Query(default=None),
    userEmail: str | None = Query(default=None),
) -> dict:
    db = request.app.state.db
    job_where, job_params = _job_filters(
        date_from=dateFrom,
        date_to=dateTo,
        file_type=fileType,
        source_lang=sourceLang,
        target_lang=targetLang,
        user_email=userEmail,
    )
    tm_where, tm_params = _tm_filters(
        date_from=dateFrom,
        date_to=dateTo,
        file_type=fileType,
        source_lang=sourceLang,
        target_lang=targetLang,
        user_email=userEmail,
    )

    tm_rows = db.query_all(
        f"""
        SELECT result_json, substr(created_at, 1, 10) AS created_day
        FROM jobs j
        WHERE {job_where}
        """,
        tuple(job_params),
    )
    trend_map: dict[str, dict[str, int]] = defaultdict(lambda: {
        "hits": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "pruned": 0,
    })
    for row in tm_rows:
        result = _parse_json(row["result_json"])
        bucket = trend_map[str(row["created_day"] or "unknown")]
        bucket["hits"] += int(result.get("tmHits", 0) or 0)
        bucket["inserted"] += int(result.get("tmInserted", 0) or 0)
        bucket["updated"] += int(result.get("tmUpdated", 0) or 0)
        bucket["skipped"] += int(result.get("tmSkipped", 0) or 0)
        bucket["pruned"] += int(result.get("tmPruned", 0) or 0)

    tier_rows = db.query_all(
        f"""
        SELECT quality_tier, COUNT(*) AS count
        FROM translation_memory tm
        WHERE {tm_where}
        GROUP BY quality_tier
        ORDER BY count DESC
        """,
        tuple(tm_params),
    )
    scope_rows = db.query_all(
        f"""
        SELECT scope, COUNT(*) AS count
        FROM translation_memory tm
        WHERE {tm_where}
        GROUP BY scope
        ORDER BY count DESC
        """,
        tuple(tm_params),
    )
    hit_rows = db.query_all(
        f"""
        SELECT source_text, target_text, scope, quality_tier, hit_count
        FROM translation_memory tm
        WHERE {tm_where}
        ORDER BY hit_count DESC, updated_at DESC
        LIMIT 20
        """,
        tuple(tm_params),
    )

    scope_counts = Counter()
    for row in scope_rows:
        scope_counts[_scope_family(str(row["scope"] or ""))] += int(row["count"] or 0)

    return {
        "qualityTiers": [{"key": row["quality_tier"], "count": int(row["count"])} for row in tier_rows],
        "scopeFamilies": [{"key": key, "count": count} for key, count in scope_counts.most_common()],
        "trend": [
            {"date": key, **trend_map[key]}
            for key in sorted(trend_map)
        ],
        "topHits": [
            {
                "sourceText": row["source_text"],
                "targetText": row["target_text"],
                "scope": row["scope"],
                "scopeFamily": _scope_family(str(row["scope"] or "")),
                "qualityTier": row["quality_tier"],
                "hitCount": int(row["hit_count"] or 0),
            }
            for row in hit_rows
        ],
    }


@router.get("/api/admin/quality/issues")
async def quality_issues(
    request: Request,
    _: CurrentUser = Depends(require_super_admin),
    dateFrom: str | None = Query(default=None),
    dateTo: str | None = Query(default=None),
    fileType: str | None = Query(default=None),
    sourceLang: str | None = Query(default=None),
    targetLang: str | None = Query(default=None),
    userEmail: str | None = Query(default=None),
    failedOnly: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=200),
) -> dict:
    db = request.app.state.db
    job_where, job_params = _job_filters(
        date_from=dateFrom,
        date_to=dateTo,
        file_type=fileType,
        source_lang=sourceLang,
        target_lang=targetLang,
        user_email=userEmail,
    )
    issue_where = job_where
    params = list(job_params)
    if failedOnly:
        issue_where += " AND js.qa_pass = 0"
    count = int(
        db.query_value(
            f"""
            SELECT COUNT(*)
            FROM job_segments js
            JOIN jobs j ON j.id = js.job_id
            WHERE {issue_where}
            """,
            tuple(params),
        )
        or 0
    )
    offset = (page - 1) * pageSize
    rows = db.query_all(
        f"""
        SELECT
            js.job_id,
            js.segment_id,
            js.segment_order,
            js.source_text,
            js.draft_translation,
            js.qa_pass,
            js.qa_reason,
            js.from_cache,
            js.tm_quality,
            js.qa_debug_json,
            j.user_id,
            j.created_at,
            j.finished_at,
            json_extract(j.payload_json, '$.fileName') AS file_name,
            json_extract(j.payload_json, '$.sourceLang') AS source_lang,
            json_extract(j.payload_json, '$.targetLang') AS target_lang,
            json_extract(j.result_json, '$.fileType') AS file_type
        FROM job_segments js
        JOIN jobs j ON j.id = js.job_id
        WHERE {issue_where}
        ORDER BY j.created_at DESC, js.segment_order ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [pageSize, offset]),
    )

    items = []
    for row in rows:
        qa_debug = _parse_json(row["qa_debug_json"])
        items.append(
            {
                "jobId": row["job_id"],
                "segmentId": row["segment_id"],
                "segmentOrder": int(row["segment_order"] or 0),
                "fileName": row["file_name"] or "",
                "fileType": row["file_type"] or "",
                "userEmail": row["user_id"] or "",
                "sourceLang": row["source_lang"] or "",
                "targetLang": row["target_lang"] or "",
                "sourceText": row["source_text"] or "",
                "draftTranslation": row["draft_translation"] or "",
                "qaPass": bool(row["qa_pass"]),
                "qaReason": row["qa_reason"],
                "qaRuleName": qa_debug.get("finalRuleName"),
                "qaFailureType": qa_debug.get("finalFailureType"),
                "fromCache": bool(row["from_cache"]),
                "tmQuality": int(row["tm_quality"] or 0),
                "createdAt": row["created_at"],
                "finishedAt": row["finished_at"],
            }
        )

    return {
        "items": items,
        "pagination": {
            "page": page,
            "pageSize": pageSize,
            "total": count,
        },
    }
