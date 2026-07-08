from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Iterable

from database import Database

_INLINE_MARKER_RE = re.compile(r"\*{1,3}|~~")
_WHITESPACE_RE = re.compile(r"\s+")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_ID_OR_CODE_RE = re.compile(r"^(?:[A-Za-z]{0,4}\d+(?:\.\d+)*|[A-Za-z]+-\d+(?:\.\d+)*|[A-Z]{1,6}\d*)$")
_SENTENCE_PUNCT_RE = re.compile(r"[.!?;。！？；]")
_CLAUSE_PUNCT_RE = re.compile(r"[,，、:：;；]")
_DIRECT_REUSE_TIERS = {"human_confirmed", "qa_passed_clean"}
_WEAK_REUSE_TIERS = {"human_confirmed", "qa_passed_clean", "model_generated"}
_QUALITY_TIER_PRIORITY = {
    "repaired_or_risky": 0,
    "model_generated": 1,
    "qa_passed_clean": 2,
    "human_confirmed": 3,
}


def _segment_plain_text(segment: dict[str, Any]) -> str:
    return str(segment.get("plain_text") or segment.get("source_text") or "").strip()


def classify_tm_segment(segment: dict[str, Any]) -> str:
    text = _segment_plain_text(segment)
    if not text:
        return "empty"

    segment_type = str(segment.get("segment_type") or "").lower()
    style_name = str(segment.get("style_name") or "").strip().lower().replace(" ", "_")
    has_latin = bool(_LATIN_RE.search(text))
    has_cjk = bool(_CJK_RE.search(text))
    word_count = len(re.findall(r"\w+", text))
    clause_punct_count = len(_CLAUSE_PUNCT_RE.findall(text))
    sentence_punct_count = len(_SENTENCE_PUNCT_RE.findall(text))

    if _ID_OR_CODE_RE.fullmatch(text):
        return "id_or_code"
    if has_latin and has_cjk:
        return "mixed_language"
    if segment_type in {"title", "sheet_title"} or "heading" in style_name or "title" in style_name:
        return "title_heading"
    if len(text) >= 80 or word_count >= 16 or sentence_punct_count > 1 or clause_punct_count >= 3 or "\n" in text:
        return "long_paragraph"
    if len(text) <= 24 and word_count <= 4 and clause_punct_count == 0:
        return "short_label"
    return "sentence"


def tm_segment_type_key(segment: dict[str, Any]) -> str:
    segment_type = str(segment.get("segment_type") or "").strip().lower()
    if segment_type in {"title", "sheet_title", "paragraph", "cell"}:
        return segment_type
    return "paragraph"


def _normalize_quality_tier(value: str | None) -> str:
    tier = str(value or "").strip().lower()
    return tier if tier in _QUALITY_TIER_PRIORITY else "model_generated"


def _candidate_quality_tier(
    candidate: dict[str, Any] | None = None,
    *,
    quality_tier: str | None = None,
    origin: str | None = None,
) -> str:
    raw_tier = str(quality_tier if quality_tier is not None else (candidate or {}).get("quality_tier") or "").strip()
    if raw_tier:
        return _normalize_quality_tier(raw_tier)

    candidate_origin = str(origin if origin is not None else (candidate or {}).get("origin") or "").strip().lower()
    if candidate_origin == "human_confirmed":
        return "human_confirmed"
    if candidate_origin == "qa_passed":
        return "qa_passed_clean"
    if candidate_origin == "repair":
        return "repaired_or_risky"

    # Backward-compatible fallback for older TM rows/tests that predate
    # quality_tier persistence. Those entries were historically treated as
    # clean QA-passed content rather than weak model-generated drafts.
    return "qa_passed_clean"


def _tier_priority(tier: str | None) -> int:
    return _QUALITY_TIER_PRIORITY[_normalize_quality_tier(tier)]


def should_direct_reuse_tier(quality_tier: str | None) -> bool:
    return _normalize_quality_tier(quality_tier) in _DIRECT_REUSE_TIERS


def should_consider_weak_reuse_tier(quality_tier: str | None) -> bool:
    return _normalize_quality_tier(quality_tier) in _WEAK_REUSE_TIERS


def can_direct_use_tm(segment: dict[str, Any]) -> bool:
    return classify_tm_segment(segment) == "short_label"


def _can_direct_reuse_hit(hit: dict[str, Any]) -> bool:
    quality_tier = _normalize_quality_tier(hit.get("quality_tier"))
    if should_direct_reuse_tier(quality_tier):
        return True
    return quality_tier == "model_generated" and str(hit.get("origin") or "").strip().lower() == "qa_passed"


def can_consider_weak_tm(segment: dict[str, Any]) -> bool:
    content_class = classify_tm_segment(segment)
    text = _segment_plain_text(segment)
    word_count = len(re.findall(r"\w+", text))
    clause_punct_count = len(_CLAUSE_PUNCT_RE.findall(text))
    sentence_punct_count = len(_SENTENCE_PUNCT_RE.findall(text))

    if content_class == "title_heading":
        return len(text) <= 80 and sentence_punct_count == 0 and "\n" not in text
    if content_class == "sentence":
        return len(text) <= 160 and word_count <= 24 and clause_punct_count <= 2 and sentence_punct_count <= 1 and "\n" not in text
    return False


def review_weak_tm_candidate_rule(segment: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, str | None]:
    source = normalize_tm_source(str(segment.get("source_text") or ""))
    translation = normalize_tm_source(str(candidate.get("translation") or ""))
    quality_tier = _candidate_quality_tier(candidate)
    if not source or not translation:
        return "reject", "TM candidate is missing required text"
    if source == translation:
        return "reject", "TM candidate matches the source and cannot be reused"
    if quality_tier == "repaired_or_risky":
        return "reject", "TM candidate is marked as repaired or risky"
    if not should_consider_weak_reuse_tier(quality_tier):
        return "reject", "TM candidate quality tier is not eligible for weak reuse"

    content_class = classify_tm_segment(segment)
    text = _segment_plain_text(segment)
    word_count = len(re.findall(r"\w+", text))
    clause_punct_count = len(_CLAUSE_PUNCT_RE.findall(text))
    sentence_punct_count = len(_SENTENCE_PUNCT_RE.findall(text))

    if content_class == "title_heading":
        if len(text) <= 30 and word_count <= 5 and clause_punct_count == 0 and should_direct_reuse_tier(quality_tier):
            return "accept", None
        return "uncertain", "Title candidate needs local context confirmation"
    if content_class == "sentence":
        if len(text) > 120 or word_count > 20 or clause_punct_count >= 2 or sentence_punct_count > 1:
            return "reject", "Sentence candidate is too context-sensitive for TM reuse"
        return "uncertain", "Sentence candidate needs semantic confirmation"
    return "reject", "Current content class is not eligible for weak TM reuse"


def _has_failed_qa_history(result: dict[str, Any]) -> bool:
    qa_debug = result.get("qa_debug") or {}
    history = qa_debug.get("history") or []
    return any(not bool(item.get("qaPass")) for item in history)


def normalize_tm_source(text: str) -> str:
    normalized = _INLINE_MARKER_RE.sub("", text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def hash_tm_source(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def normalize_tm_scopes(scopes: str | Iterable[str] | None) -> list[str]:
    if scopes is None:
        return ["global"]
    if isinstance(scopes, str):
        raw_scopes = [scopes]
    else:
        raw_scopes = list(scopes)

    normalized: list[str] = []
    for scope in raw_scopes:
        value = str(scope or "").strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized or ["global"]


def tm_quality_tier_for_result(result: dict[str, Any]) -> str:
    explicit = _normalize_quality_tier(result.get("quality_tier"))
    if explicit != "model_generated" or str(result.get("quality_tier") or "").strip():
        return explicit
    if bool(result.get("human_confirmed")):
        return "human_confirmed"
    if _has_failed_qa_history(result):
        return "repaired_or_risky"
    if bool(result.get("qa_pass")):
        return "qa_passed_clean"
    return "model_generated"


def should_store_tm_segment(segment: dict[str, Any], result: dict[str, Any]) -> bool:
    if not bool(result.get("qa_pass")):
        return False
    if bool(result.get("from_cache")):
        return False

    source_text = str(segment.get("source_text") or "")
    target_text = str(result.get("draft_translation") or "")
    source_plain = normalize_tm_source(source_text)
    target_plain = normalize_tm_source(target_text)
    if len(source_plain) < 3 or len(source_plain) > 2000:
        return False
    if not target_plain:
        return False
    if source_plain.isdigit():
        return False
    if re.fullmatch(r"[\W_]+", source_plain):
        return False
    if source_plain == target_plain:
        return False
    if _has_failed_qa_history(result):
        return False
    if tm_quality_tier_for_result(result) == "repaired_or_risky":
        return False

    segment_class = classify_tm_segment(segment)
    if segment_class in {"id_or_code", "long_paragraph", "mixed_language", "empty"}:
        return False
    return True


def tm_quality_for_result(result: dict[str, Any]) -> int:
    if result.get("from_cache"):
        return max(int(result.get("tm_quality", 0)), 95)
    if result.get("human_confirmed"):
        return max(int(result.get("tm_quality", 0)), 98)
    if _has_failed_qa_history(result):
        return max(int(result.get("tm_quality", 0)), 70)
    if result.get("qa_pass"):
        return max(int(result.get("tm_quality", 0)), 90)
    return int(result.get("tm_quality", 0) or 0)


def _lookup_tm_entry(
    db: Database,
    segment: dict[str, Any],
    source_lang: str,
    target_lang: str,
    scopes: list[str],
) -> dict[str, Any] | None:
    normalized_source = normalize_tm_source(segment["source_text"])
    if not normalized_source:
        return None

    segment_type = tm_segment_type_key(segment)
    content_class = classify_tm_segment(segment)
    source_hash = hash_tm_source(normalized_source)

    for scope in scopes:
        row = db.query_one(
            """
            SELECT scope, target_text, quality, quality_tier, source_hash, segment_type, content_class, origin
            FROM translation_memory
            WHERE scope = ? AND source_lang = ? AND target_lang = ? AND source_hash = ?
              AND segment_type = ? AND content_class = ?
            LIMIT 1
            """,
            (scope, source_lang, target_lang, source_hash, segment_type, content_class),
        )
        if row is None:
            continue
        return {
            "translation": row["target_text"],
            "quality": int(row["quality"] or 0),
            "quality_tier": _candidate_quality_tier(
                quality_tier=row["quality_tier"],
                origin=row["origin"],
            ),
            "origin": row["origin"],
            "source_hash": row["source_hash"],
            "segment_type": row["segment_type"],
            "content_class": row["content_class"],
            "scope": scope,
            "source_text_normalized": normalized_source,
            "from_cache": True,
        }
    return None


def lookup_tm_segments(
    db: Database,
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    scopes: str | Iterable[str] = "global",
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    cache_hits: dict[str, dict[str, Any]] = {}
    misses: list[dict] = []
    ordered_scopes = normalize_tm_scopes(scopes)

    for segment in segments:
        if not can_direct_use_tm(segment):
            misses.append(segment)
            continue

        hit = _lookup_tm_entry(db, segment, source_lang, target_lang, ordered_scopes)
        if hit is None or not _can_direct_reuse_hit(hit):
            misses.append(segment)
            continue
        cache_hits[segment["id"]] = hit

    return cache_hits, misses


def lookup_tm_candidate_segments(
    db: Database,
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    scopes: str | Iterable[str] = "global",
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    candidates: dict[str, dict[str, Any]] = {}
    misses: list[dict] = []
    ordered_scopes = normalize_tm_scopes(scopes)

    for segment in segments:
        if not can_consider_weak_tm(segment):
            misses.append(segment)
            continue

        hit = _lookup_tm_entry(db, segment, source_lang, target_lang, ordered_scopes)
        if hit is None or not should_consider_weak_reuse_tier(hit.get("quality_tier")):
            misses.append(segment)
            continue
        candidates[segment["id"]] = hit

    return candidates, misses


def mark_tm_hits(
    db: Database,
    hit_records: dict[str, dict[str, Any]],
    used_by: str | None,
    now: str,
) -> None:
    for item in hit_records.values():
        db.execute(
            """
            UPDATE translation_memory
            SET hit_count = hit_count + 1,
                last_hit_at = ?,
                last_used_by = ?
            WHERE scope = ? AND source_hash = ? AND segment_type = ? AND content_class = ?
            """,
            (now, used_by, item["scope"], item["source_hash"], item["segment_type"], item["content_class"]),
        )


def store_tm_segments(
    db: Database,
    segments: list[dict],
    translated: list[dict],
    source_lang: str,
    target_lang: str,
    user_id: str | None,
    now: str,
    scopes: str | Iterable[str] = "global",
) -> dict[str, int]:
    stats = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
    }
    translated_by_id = {item["id"]: item for item in translated}
    write_scopes = normalize_tm_scopes(scopes)

    for segment in segments:
        result = translated_by_id.get(segment["id"])
        if not result:
            continue
        if not should_store_tm_segment(segment, result):
            stats["skipped"] += 1
            continue

        source_text = segment["source_text"]
        normalized_source = normalize_tm_source(source_text)
        source_hash = hash_tm_source(normalized_source)
        segment_type = tm_segment_type_key(segment)
        content_class = classify_tm_segment(segment)
        target_text = str(result.get("draft_translation") or "")
        quality = tm_quality_for_result(result)
        quality_tier = tm_quality_tier_for_result(result)
        origin = "human_confirmed" if quality_tier == "human_confirmed" else "qa_passed"
        if quality <= 0:
            stats["skipped"] += 1
            continue

        segment_inserted = False
        segment_updated = False
        for scope in write_scopes:
            existing = db.query_one(
                """
                SELECT id, source_text, source_text_normalized, target_text, quality, quality_tier
                FROM translation_memory
                WHERE scope = ? AND source_lang = ? AND target_lang = ? AND source_hash = ?
                  AND segment_type = ? AND content_class = ?
                LIMIT 1
                """,
                (scope, source_lang, target_lang, source_hash, segment_type, content_class),
            )

            if existing is not None:
                existing_tier = _normalize_quality_tier(existing["quality_tier"])
                unchanged = (
                    (existing["source_text"] or "") == source_text
                    and (existing["source_text_normalized"] or "") == normalized_source
                    and (existing["target_text"] or "") == target_text
                    and int(existing["quality"] or 0) >= quality
                    and _tier_priority(existing_tier) >= _tier_priority(quality_tier)
                )
                if unchanged:
                    continue

            db.execute(
                """
                INSERT INTO translation_memory (
                    id,
                    scope,
                    source_lang,
                    target_lang,
                    source_hash,
                    segment_type,
                    content_class,
                    source_text,
                    source_text_normalized,
                    target_text,
                    quality,
                    quality_tier,
                    created_by,
                    hit_count,
                    last_hit_at,
                    last_used_by,
                    origin,
                    locked,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, 0, ?, ?)
                ON CONFLICT(scope, source_lang, target_lang, source_hash, segment_type, content_class) DO UPDATE SET
                    source_text = CASE
                        WHEN translation_memory.quality_tier = 'human_confirmed' AND excluded.quality_tier != 'human_confirmed'
                            THEN translation_memory.source_text
                        ELSE excluded.source_text
                    END,
                    source_text_normalized = CASE
                        WHEN translation_memory.quality_tier = 'human_confirmed' AND excluded.quality_tier != 'human_confirmed'
                            THEN translation_memory.source_text_normalized
                        ELSE excluded.source_text_normalized
                    END,
                    target_text = CASE
                        WHEN translation_memory.quality_tier = 'human_confirmed' AND excluded.quality_tier != 'human_confirmed'
                            THEN translation_memory.target_text
                        ELSE excluded.target_text
                    END,
                    quality = CASE
                        WHEN translation_memory.quality_tier = 'human_confirmed' AND excluded.quality_tier != 'human_confirmed'
                            THEN translation_memory.quality
                        WHEN excluded.quality >= translation_memory.quality THEN excluded.quality
                        ELSE translation_memory.quality
                    END,
                    quality_tier = CASE
                        WHEN translation_memory.quality_tier = 'human_confirmed' THEN translation_memory.quality_tier
                        WHEN excluded.quality_tier = 'human_confirmed' THEN excluded.quality_tier
                        WHEN excluded.quality >= translation_memory.quality THEN excluded.quality_tier
                        ELSE translation_memory.quality_tier
                    END,
                    created_by = COALESCE(translation_memory.created_by, excluded.created_by),
                    origin = CASE
                        WHEN translation_memory.quality_tier = 'human_confirmed' THEN translation_memory.origin
                        WHEN excluded.quality_tier = 'human_confirmed' THEN excluded.origin
                        WHEN excluded.quality >= translation_memory.quality THEN excluded.origin
                        ELSE translation_memory.origin
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    str(existing["id"]) if existing is not None else str(uuid.uuid4()),
                    scope,
                    source_lang,
                    target_lang,
                    source_hash,
                    segment_type,
                    content_class,
                    source_text,
                    normalized_source,
                    target_text,
                    quality,
                    quality_tier,
                    user_id,
                    origin,
                    now,
                    now,
                ),
            )
            if existing is None:
                segment_inserted = True
            else:
                segment_updated = True

        if segment_inserted:
            stats["inserted"] += 1
        elif segment_updated:
            stats["updated"] += 1
        else:
            stats["skipped"] += 1

    return stats


def prune_translation_memory(
    db: Database,
    max_entries: int,
    prune_batch_size: int,
) -> int:
    if max_entries <= 0:
        return 0
    total = db.query_value("SELECT COUNT(*) FROM translation_memory") or 0
    overflow = total - max_entries
    if overflow <= 0:
        return 0

    delete_count = max(overflow, prune_batch_size if prune_batch_size > 0 else overflow)
    rows = db.query_all(
        """
        SELECT id
        FROM translation_memory
        WHERE locked = 0
        ORDER BY
            CASE quality_tier
                WHEN 'repaired_or_risky' THEN 0
                WHEN 'model_generated' THEN 1
                WHEN 'qa_passed_clean' THEN 2
                WHEN 'human_confirmed' THEN 3
                ELSE 1
            END ASC,
            quality ASC,
            hit_count ASC,
            CASE WHEN last_hit_at IS NULL THEN 0 ELSE 1 END ASC,
            COALESCE(last_hit_at, updated_at, created_at) ASC
        LIMIT ?
        """,
        (delete_count,),
    )
    if not rows:
        return 0

    deleted = 0
    for row in rows:
        db.execute("DELETE FROM translation_memory WHERE id = ?", (row["id"],))
        deleted += 1
    return deleted
