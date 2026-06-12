"""Dashboard statistics endpoint.

Returns real data aggregated from the database for the home page.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from auth.middleware import CurrentUser, get_current_user


router = APIRouter()


@router.get("/api/dashboard/stats")
async def dashboard_stats(
    request: Request,
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    db = request.app.state.db

    # ── Glossary counts ───────────────────────────────────────────────────────
    glossary_total = db.query_value("SELECT COUNT(*) FROM glossary_terms") or 0
    glossary_enabled = db.query_value("SELECT COUNT(*) FROM glossary_terms WHERE enabled = 1") or 0

    # ── Translation memory ────────────────────────────────────────────────────
    tm_total = db.query_value("SELECT COUNT(*) FROM translation_memory") or 0

    # ── Jobs (all-time) ───────────────────────────────────────────────────────
    jobs_total = db.query_value("SELECT COUNT(*) FROM jobs WHERE type = 'translation'") or 0
    jobs_succeeded = db.query_value(
        "SELECT COUNT(*) FROM jobs WHERE type = 'translation' AND status = 'succeeded'"
    ) or 0

    # ── Jobs by lang pair (top 5) ─────────────────────────────────────────────
    lang_pair_rows = db.query_all(
        """
        SELECT
            json_extract(payload_json, '$.sourceLang') AS src,
            json_extract(payload_json, '$.targetLang') AS tgt,
            COUNT(*) AS cnt
        FROM jobs
        WHERE type = 'translation'
          AND status = 'succeeded'
          AND payload_json IS NOT NULL
        GROUP BY src, tgt
        ORDER BY cnt DESC
        LIMIT 5
        """
    )

    # ── Most used glossary terms (appear in TM source texts) ─────────────────
    # Strategy: for each enabled glossary term, count how many TM entries
    # contain that source_term in their source_text. Limit to top 20 terms.
    glossary_terms = db.query_all(
        """
        SELECT id, source_term, target_term, source_lang, target_lang
        FROM glossary_terms
        WHERE enabled = 1
        ORDER BY priority DESC, length(source_term) DESC
        LIMIT 100
        """
    )

    hit_counts: list[dict] = []
    for term in glossary_terms:
        count = db.query_value(
            """
            SELECT COUNT(*) FROM translation_memory
            WHERE source_lang = ? AND target_lang = ?
              AND source_text LIKE ?
            """,
            (term["source_lang"], term["target_lang"], f"%{term['source_term']}%"),
        ) or 0
        if count > 0:
            hit_counts.append({
                "sourceTerm": term["source_term"],
                "targetTerm": term["target_term"],
                "sourceLang": term["source_lang"],
                "targetLang": term["target_lang"],
                "hitCount": int(count),
            })

    hit_counts.sort(key=lambda x: -x["hitCount"])
    top_terms = hit_counts[:20]

    # ── Recent 10 translation jobs ────────────────────────────────────────────
    recent_jobs = db.query_all(
        """
        SELECT id, status, progress, payload_json, result_json, created_at, finished_at
        FROM jobs
        WHERE type = 'translation'
        ORDER BY created_at DESC
        LIMIT 10
        """
    )

    return {
        "glossary": {
            "total": int(glossary_total),
            "enabled": int(glossary_enabled),
        },
        "translationMemory": {
            "total": int(tm_total),
        },
        "jobs": {
            "total": int(jobs_total),
            "succeeded": int(jobs_succeeded),
        },
        "langPairs": [
            {"src": row["src"], "tgt": row["tgt"], "count": row["cnt"]}
            for row in lang_pair_rows
            if row["src"] and row["tgt"]
        ],
        "topTerms": top_terms,
        "recentJobs": [
            {
                "id": row["id"],
                "status": row["status"],
                "fileName": (json.loads(row["payload_json"]) or {}).get("fileName", "—") if row["payload_json"] else "—",
                "sourceLang": (json.loads(row["payload_json"]) or {}).get("sourceLang", "") if row["payload_json"] else "",
                "targetLang": (json.loads(row["payload_json"]) or {}).get("targetLang", "") if row["payload_json"] else "",
                "createdAt": row["created_at"],
                "finishedAt": row["finished_at"],
            }
            for row in recent_jobs
        ],
    }
