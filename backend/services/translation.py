from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable

from services.bedrock import translate_batch_bedrock
from services.docx.markup import clean_translation_artifacts, normalize_marker_spacing, preserve_circled_prefix
from services.glossary_matcher import (
    apply_glossary_postprocess,
    terms_for_source,
)
from services.qa_ai import adjudicate_tm_candidates
from services.qa import check_required_terms
from services.qa_hybrid import evaluate_segments_qa_with_repair
from services.translation_align import (
    is_source_already_target_language,
    is_translation_required,
    is_universal_notranslate_expression,
    needs_retranslation,
)
from services.tm import (
    lookup_tm_candidate_segments,
    lookup_tm_segments,
    mark_tm_hits,
    prune_translation_memory,
    review_weak_tm_candidate_rule,
    store_tm_segments,
)

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 5       # max simultaneous Bedrock requests
_ZH_HEADING_DIGIT_ENUM_RE = re.compile(r"^(\d+(?:\.\d+)*)、\s*")
_ZH_HEADING_CJK_ENUM_RE = re.compile(r"^([一二三四五六七八九十]+)、\s*")
def _accept_tm_ai_verdict(pass_: bool, confidence: float, threshold: float) -> bool:
    return bool(pass_) and float(confidence) >= threshold


def _normalize_heading_enumeration(source: str, translation: str, target_lang: str) -> str:
    if not target_lang.startswith("en"):
        return translation

    if _ZH_HEADING_DIGIT_ENUM_RE.match(source):
        return _ZH_HEADING_DIGIT_ENUM_RE.sub(r"\1. ", translation, count=1)

    if _ZH_HEADING_CJK_ENUM_RE.match(source):
        return _ZH_HEADING_CJK_ENUM_RE.sub(r"\1. ", translation, count=1)

    return translation


def _finalize_draft(source: str, translation: str, target_lang: str = "") -> str:
    text = preserve_circled_prefix(source, translation or "")
    text = normalize_marker_spacing(text)
    text = _normalize_heading_enumeration(source, text, target_lang)
    # Fix model-added illegal spaces inside grouped numbers before QA.
    text = re.sub(r"(?:,|\uFF0C)\s(?=\d{3}\b)", ",", text)
    return clean_translation_artifacts(text, target_lang=target_lang)


def _normalize_style_name(style_name: str | None) -> str:
    return (style_name or "").strip().lower().replace(" ", "_")


def _segment_plain_text(segment: dict) -> str:
    return str(segment.get("plain_text") or segment.get("source_text") or "").strip()


def _is_short_label_text(text: str) -> bool:
    words = re.findall(r"\w+", text)
    return len(text) <= 20 and len(words) <= 4


def _segment_kind(segment: dict) -> str:
    segment_type = str(segment.get("segment_type") or "").lower()
    style_name = _normalize_style_name(segment.get("style_name"))
    md_location_type = str((segment.get("_md_location") or {}).get("type") or "").lower()
    plain_text = _segment_plain_text(segment)

    if segment_type == "title" or "heading" in style_name or "title" in style_name:
        return "title"
    if segment_type == "sheet_title":
        return "title"
    if style_name in {"list", "blockquote"} or md_location_type in {"list_item", "blockquote"}:
        return "structured"
    if _is_short_label_text(plain_text):
        return "label"
    if segment_type == "cell" or style_name == "table_cell" or md_location_type == "table_cell":
        if len(plain_text) >= 40 or len(re.findall(r"\w+", plain_text)) >= 8:
            return "table_text"
        return "table"
    return "paragraph"


def _segment_group_key(segment: dict) -> str:
    kind = _segment_kind(segment)
    style_name = _normalize_style_name(segment.get("style_name"))
    if kind in {"title", "table", "structured"}:
        return f"{kind}:{style_name or kind}"
    return kind


def _is_oversized_segment(segment: dict, max_bytes: int) -> bool:
    plain_text = _segment_plain_text(segment)
    segment_bytes = len(plain_text.encode("utf-8"))
    return segment_bytes >= max(1200, int(max_bytes * 0.45)) or len(plain_text) >= 500


def _batch_limits_for_group(group_key: str, max_bytes: int, max_segments: int) -> tuple[int, int]:
    kind = group_key.split(":", 1)[0]
    if kind == "title":
        return max(600, int(max_bytes * 0.20)), min(max_segments, 8)
    if kind == "table":
        return max(1200, int(max_bytes * 0.30)), min(max_segments, 24)
    if kind == "table_text":
        return max(900, int(max_bytes * 0.22)), min(max_segments, 4)
    if kind == "structured":
        return max(1600, int(max_bytes * 0.40)), min(max_segments, 18)
    if kind == "label":
        return max(1000, int(max_bytes * 0.25)), min(max_segments, 40)
    return max_bytes, max_segments


def _xlsx_batch_family(segment: dict) -> str:
    kind = _segment_kind(segment)
    plain_text = _segment_plain_text(segment)
    word_count = len(re.findall(r"\w+", plain_text))
    requires_translation = is_translation_required(plain_text)

    if not requires_translation:
        return "passthrough"
    if kind in {"label", "title"}:
        return "label"
    if kind == "table" and len(plain_text) <= 32 and word_count <= 5:
        return "short_text"
    if len(plain_text) <= 24 and word_count <= 4:
        return "short_text"
    if len(plain_text) >= 40 or word_count >= 8:
        return "long_text"
    return "content"


def _split_xlsx_batches(
    segments: list[dict],
    max_bytes: int,
    max_segments: int,
) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_bytes = 0
    current_family = ""

    def flush_current_batch() -> None:
        nonlocal current_batch, current_bytes, current_family
        if current_batch:
            batches.append(current_batch[:])
        current_batch = []
        current_bytes = 0
        current_family = ""

    for segment in segments:
        text = segment["source_text"]
        segment_bytes = len(text.encode("utf-8"))
        family = _xlsx_batch_family(segment)

        if segment_bytes > max_bytes or _is_oversized_segment(segment, max_bytes):
            flush_current_batch()
            batches.append([segment])
            continue

        if family == "passthrough":
            family_max_bytes = min(max_bytes, 3200)
            family_max_segments = min(max_segments, 18)
        elif family == "label":
            family_max_bytes = min(max_bytes, 2200)
            family_max_segments = min(max_segments, 12)
        elif family == "short_text":
            family_max_bytes = min(max_bytes, 2200)
            family_max_segments = min(max_segments, 8)
        elif family == "long_text":
            family_max_bytes = min(max_bytes, 3200)
            family_max_segments = min(max_segments, 4)
        else:
            family_max_bytes = min(max_bytes, 3600)
            family_max_segments = min(max_segments, 6)

        if not current_batch:
            current_family = family
        elif (
            family != current_family
            or current_bytes + segment_bytes > family_max_bytes
            or len(current_batch) >= family_max_segments
        ):
            flush_current_batch()
            current_family = family

        current_batch.append(segment)
        current_bytes += segment_bytes

    flush_current_batch()
    return batches


def _split_into_simple_batches(
    segments: list[dict],
    max_bytes: int,
    max_segments: int,
) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_bytes = 0

    def flush_current_batch() -> None:
        nonlocal current_batch, current_bytes
        if current_batch:
            batches.append(current_batch)
        current_batch = []
        current_bytes = 0

    for segment in segments:
        text = segment["source_text"]
        segment_bytes = len(text.encode("utf-8"))

        if segment_bytes > max_bytes or _is_oversized_segment(segment, max_bytes):
            flush_current_batch()
            batches.append([segment])
            continue

        if current_batch and (
            current_bytes + segment_bytes > max_bytes
            or len(current_batch) >= max_segments
        ):
            flush_current_batch()

        current_batch.append(segment)
        current_bytes += segment_bytes

    flush_current_batch()
    return batches


def _split_into_batches(
    segments: list[dict],
    max_bytes: int,
    max_segments: int,
    *,
    file_type: str = "",
) -> list[list[dict]]:
    """Split segments into structure-aware, byte-bounded translation batches."""
    if file_type in {"xlsx", "docx", "md"}:
        # Keep document-style files coarse to reduce request count and latency.
        return _split_into_simple_batches(segments, max_bytes, min(max_segments, 50))

    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_bytes: int = 0
    current_group_key = ""
    current_max_bytes = max_bytes
    current_max_segments = max_segments

    def flush_current_batch() -> None:
        nonlocal current_batch, current_bytes, current_group_key, current_max_bytes, current_max_segments
        if current_batch:
            batches.append(current_batch)
        current_batch = []
        current_bytes = 0
        current_group_key = ""
        current_max_bytes = max_bytes
        current_max_segments = max_segments

    for segment in segments:
        text = segment["source_text"]
        segment_bytes = len(text.encode("utf-8"))
        segment_group_key = _segment_group_key(segment)
        segment_max_bytes, segment_max_segments = _batch_limits_for_group(
            segment_group_key,
            max_bytes,
            max_segments,
        )

        if segment_bytes > max_bytes or _is_oversized_segment(segment, max_bytes):
            flush_current_batch()
            batches.append([segment])
            continue

        if not current_batch:
            current_group_key = segment_group_key
            current_max_bytes = segment_max_bytes
            current_max_segments = segment_max_segments
        elif (
            segment_group_key != current_group_key
            or current_bytes + segment_bytes > current_max_bytes
            or len(current_batch) >= current_max_segments
        ):
            flush_current_batch()
            current_group_key = segment_group_key
            current_max_bytes = segment_max_bytes
            current_max_segments = segment_max_segments

        current_batch.append(segment)
        current_bytes += segment_bytes

    flush_current_batch()
    return batches


def _has_malformed_thousands_separator(text: str) -> bool:
    normalized = text.replace("\u00a0", " ").replace("\u202f", " ")
    return bool(re.search(r"(?<=\d)\s*(?:,|\uFF0C)\s+(?=\d{3}(?:\D|$))", normalized))


def _should_force_single_segment_retry(
    segment: dict,
    translation: str,
    *,
    source_lang: str,
    target_lang: str,
) -> bool:
    if not translation.strip():
        return True
    if _has_malformed_thousands_separator(translation):
        return True
    return needs_retranslation(
        segment["source_text"],
        translation,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def _build_drafts_by_id(
    *,
    segments: list[dict],
    results_by_id: dict[str, dict],
    cache_hits: dict[str, dict],
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None,
) -> tuple[dict[str, str], dict[str, dict]]:
    drafts_by_id: dict[str, str] = {}
    glossary_debug_by_id: dict[str, dict] = {}
    for segment in segments:
        seg_id = segment["id"]
        raw_translation = (
            results_by_id.get(seg_id, {}).get("translation")
            or cache_hits.get(seg_id, {}).get("translation")
            or ""
        )
        draft = _finalize_draft(segment["source_text"], raw_translation, target_lang)
        matched_terms = terms_for_source(glossary_terms or [], segment["source_text"], source_lang, target_lang)
        before_postprocess = draft
        if matched_terms:
            draft = apply_glossary_postprocess(
                source=segment["source_text"],
                translation=draft,
                terms=matched_terms,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        drafts_by_id[seg_id] = draft
        glossary_debug_by_id[seg_id] = {
            "matchedTerms": matched_terms,
            "postprocessApplied": draft != before_postprocess,
            "postprocessBefore": before_postprocess if draft != before_postprocess else None,
            "postprocessAfter": draft if draft != before_postprocess else None,
        }
    return drafts_by_id, glossary_debug_by_id


def _finalize_glossary_debug(
    *,
    segment: dict,
    translation: str,
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None,
    debug: dict | None,
) -> dict | None:
    if not debug:
        return None
    final_reason = check_required_terms(
        segment["source_text"],
        translation,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_terms=glossary_terms,
    )
    return {
        **debug,
        "finalCheckPassed": final_reason is None,
        "finalCheckReason": final_reason,
    }


def _build_translation_output(
    *,
    segments: list[dict],
    results_by_id: dict[str, dict],
    cache_hits: dict[str, dict],
    drafts_by_id: dict[str, str],
    qa_results: dict[str, dict],
    qa_profile: dict,
    glossary_debug_by_id: dict[str, dict],
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None,
) -> dict:
    translated_segments: list[dict] = []
    for segment in segments:
        raw = results_by_id.get(segment["id"]) or cache_hits.get(segment["id"], {})
        qa = qa_results.get(
            segment["id"],
            {"qa_pass": True, "qa_reason": None, "qa_rule_name": None, "qa_failure_type": None},
        )
        translated_segments.append(
            {
                "id": segment["id"],
                "draft_translation": drafts_by_id.get(segment["id"], ""),
                "from_cache": bool(raw.get("fromCache", raw.get("from_cache", False))),
                "tm_quality": int(raw.get("qualityScore", raw.get("quality", 0))),
                "qa_pass": qa["qa_pass"],
                "qa_reason": qa["qa_reason"],
                "qa_rule_name": qa.get("qa_rule_name"),
                "qa_failure_type": qa.get("qa_failure_type"),
                "qa_debug": qa.get("qa_debug"),
                "glossary_debug": _finalize_glossary_debug(
                    segment=segment,
                    translation=drafts_by_id.get(segment["id"], ""),
                    source_lang=source_lang,
                    target_lang=target_lang,
                    glossary_terms=glossary_terms,
                    debug=glossary_debug_by_id.get(segment["id"]),
                ),
            }
        )
    return {
        "segments": translated_segments,
        "qa_profile": qa_profile.get("summary"),
    }


def _normalize_xlsx_dedup_text(segment: dict) -> str:
    text = _segment_plain_text(segment)
    return re.sub(r"\s+", " ", text).strip()


def _dedupe_xlsx_segments(segments: list[dict]) -> tuple[list[dict], dict[str, str], int]:
    """Collapse repeated xlsx text segments so each unique text is translated once."""
    unique_segments: list[dict] = []
    representative_id_by_key: dict[tuple[str, str], str] = {}
    alias_to_representative: dict[str, str] = {}
    deduped_count = 0

    for segment in segments:
        segment_type = str(segment.get("segment_type") or "").strip().lower()
        if segment_type not in {"sheet_title", "cell"}:
            unique_segments.append(segment)
            continue

        key = (segment_type, _normalize_xlsx_dedup_text(segment))
        if not key[1]:
            unique_segments.append(segment)
            continue

        representative_id = representative_id_by_key.get(key)
        if representative_id is None:
            representative_id_by_key[key] = segment["id"]
            unique_segments.append(segment)
            continue

        alias_to_representative[segment["id"]] = representative_id
        deduped_count += 1

    return unique_segments, alias_to_representative, deduped_count


async def _translate_chunk_via_bedrock(
    chunk: list[dict],
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None,
    glossary_max_terms: int,
    glossary_max_prompt_chars: int,
    model_id: str,
    region: str,
    aws_profile: str | None,
) -> list[dict]:
    segments_input = [
        {
            "id": item["id"],
            "text": item["source_text"],
            "glossary": terms_for_source(glossary_terms or [], item["source_text"], source_lang, target_lang)[: min(glossary_max_terms, 8)],
            "translationRequired": is_translation_required(
                item["source_text"],
                source_lang=source_lang,
                target_lang=target_lang,
            ),
        }
        for item in chunk
    ]
    return await translate_batch_bedrock(
        segments=segments_input,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary=[],
        model_id=model_id,
        region=region,
        aws_profile=aws_profile or None,
        all_glossary_terms=glossary_terms,
    )


async def translate_segments(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    file_type: str = "",
    bearer_token: str | None = None,
    lambda_url: str = "",
    timeout_seconds: int = 30,
    glossary_terms: list[dict] | None = None,
    glossary_max_terms: int = 100,
    glossary_max_prompt_chars: int = 12000,
    batch_max_bytes: int = 5000,
    batch_max_segments: int = 120,
    bedrock_model_id: str = "us.amazon.nova-lite-v1:0",
    bedrock_region: str = "us-east-1",
    bedrock_aws_profile: str = "",
    qa_ai_enabled: bool = True,
    qa_ai_model_id: str = "us.amazon.nova-micro-v1:0",
    qa_ai_uncertain_threshold: float = 0.75,
    qa_ai_batch_max_segments: int = 40,
    qa_repair_enabled: bool = True,
    qa_repair_max_attempts: int = 1,
    qa_repair_batch_max_segments: int = 40,
    tm_weak_ai_enabled: bool = False,
    on_batch_done: "Callable[[int, int], None] | None" = None,
    db=None,
    tm_user_id: str | None = None,
    now_iso: str | None = None,
    tm_max_entries: int = 200000,
    tm_prune_batch_size: int = 5000,
    tm_lookup_scopes: list[str] | None = None,
    tm_write_scopes: list[str] | None = None,
    tm_stats: dict[str, int] | None = None,
) -> dict:
    cache_hits: dict[str, dict] = {}
    passthrough_hits: dict[str, dict] = {
        segment["id"]: {
            "translation": segment["source_text"],
            "fromCache": False,
            "qualityScore": 100,
            "passthrough": True,
        }
        for segment in segments
        if is_source_already_target_language(segment["source_text"], target_lang)
        or is_universal_notranslate_expression(segment["source_text"])
    }
    translatable_segments = [segment for segment in segments if segment["id"] not in passthrough_hits]
    misses = translatable_segments
    if tm_stats is None:
        tm_stats = {}
    tm_stats.setdefault("hits", 0)
    tm_stats.setdefault("stored", 0)
    tm_stats.setdefault("inserted", 0)
    tm_stats.setdefault("updated", 0)
    tm_stats.setdefault("skipped", 0)
    tm_stats.setdefault("pruned", 0)
    if tm_lookup_scopes is None:
        tm_lookup_scopes = ["global"]
    if tm_write_scopes is None:
        tm_write_scopes = ["global"]
    if db is not None:
        cache_hits, misses = lookup_tm_segments(
            db,
            translatable_segments,
            source_lang,
            target_lang,
            scopes=tm_lookup_scopes,
        )
        weak_candidate_source_segments = list(misses)
        weak_candidates, weak_lookup_misses = lookup_tm_candidate_segments(
            db,
            weak_candidate_source_segments,
            source_lang,
            target_lang,
            scopes=tm_lookup_scopes,
        )
        weak_hits: dict[str, dict] = {}
        weak_ai_queue: list[dict] = []
        weak_rejected_ids: set[str] = set()
        for segment in [item for item in weak_candidate_source_segments if item["id"] in weak_candidates]:
            candidate = weak_candidates[segment["id"]]
            decision, reason = review_weak_tm_candidate_rule(segment, candidate)
            if decision == "accept":
                weak_hits[segment["id"]] = candidate
                continue
            if decision == "reject":
                weak_rejected_ids.add(segment["id"])
                continue
            weak_ai_queue.append(
                {
                    "id": segment["id"],
                    "source": segment["source_text"],
                    "translation": candidate["translation"],
                    "candidate_scope": candidate.get("scope", ""),
                    "rule_reason": reason or "TM candidate needs review",
                }
            )
        if tm_weak_ai_enabled and weak_ai_queue and qa_ai_enabled and bool((qa_ai_model_id or bedrock_model_id).strip()):
            try:
                verdicts = await adjudicate_tm_candidates(
                    items=weak_ai_queue,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    model_id=qa_ai_model_id or bedrock_model_id,
                    region=bedrock_region,
                    aws_profile=bedrock_aws_profile or None,
                )
            except Exception as exc:
                logger.warning("TM candidate AI review failed: %s", exc)
                verdicts = {}
            for item in weak_ai_queue:
                verdict = verdicts.get(item["id"])
                if verdict and _accept_tm_ai_verdict(verdict.pass_, verdict.confidence, qa_ai_uncertain_threshold):
                    weak_hits[item["id"]] = weak_candidates[item["id"]]
                else:
                    weak_rejected_ids.add(item["id"])
        else:
            weak_rejected_ids.update(item["id"] for item in weak_ai_queue)

        if weak_hits:
            cache_hits = {**cache_hits, **weak_hits}
        rejected_candidate_segments = [
            segment for segment in weak_candidate_source_segments if segment["id"] in weak_rejected_ids
        ]
        misses = weak_lookup_misses + rejected_candidate_segments
        tm_stats["hits"] = len(cache_hits)
        if cache_hits and now_iso:
            mark_tm_hits(db, cache_hits, tm_user_id, now_iso)
    cache_hits = {**passthrough_hits, **cache_hits}

    xlsx_alias_to_representative: dict[str, str] = {}
    xlsx_deduped_count = 0
    if file_type == "xlsx" and misses:
        misses, xlsx_alias_to_representative, xlsx_deduped_count = _dedupe_xlsx_segments(misses)
        if xlsx_deduped_count:
            logger.info(
                "xlsx dedupe collapsed %d repeated segments into %d unique translation items",
                xlsx_deduped_count,
                len(misses),
            )

    logger.info("Translation mode: Bedrock direct (model=%s region=%s)", bedrock_model_id, bedrock_region)

    batches = _split_into_batches(
        misses,
        batch_max_bytes,
        batch_max_segments,
        file_type=file_type,
    )

    async def _retry_suspicious_segments(
        results_by_id: dict[str, dict],
        *,
        retry_one: Callable[[dict], "asyncio.Future[list[dict]]"],
    ) -> dict[str, dict]:
        retriable_segments = [
            segment
            for segment in misses
            if segment["id"] in results_by_id
            and _should_force_single_segment_retry(
                segment,
                str(results_by_id.get(segment["id"], {}).get("translation") or ""),
                source_lang=source_lang,
                target_lang=target_lang,
            )
        ]
        if not retriable_segments:
            return results_by_id

        for segment in retriable_segments:
            retried = await retry_one(segment)
            if not retried:
                continue
            candidate = retried[0]
            candidate_translation = str(candidate.get("translation") or "")
            if not candidate_translation:
                continue
            if _should_force_single_segment_retry(
                segment,
                candidate_translation,
                source_lang=source_lang,
                target_lang=target_lang,
            ):
                continue
            results_by_id[segment["id"]] = candidate
        return results_by_id

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    total_batches = len(batches)
    completed = 0
    completed_lock = asyncio.Lock()

    async def _bounded_bedrock(chunk: list[dict]) -> list[dict]:
        nonlocal completed
        result = await _translate_chunk_via_bedrock(
            chunk=chunk,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
            glossary_max_terms=glossary_max_terms,
            glossary_max_prompt_chars=glossary_max_prompt_chars,
            model_id=bedrock_model_id,
            region=bedrock_region,
            aws_profile=bedrock_aws_profile or None,
        )
        async with completed_lock:
            completed += 1
            if on_batch_done:
                on_batch_done(completed, total_batches)
        return result

    batch_results: list[list[dict]] = await asyncio.gather(
        *[_bounded_bedrock(chunk) for chunk in batches]
    )

    results_by_id: dict[str, dict] = {}
    for batch in batch_results:
        for item in batch:
            results_by_id[item["id"]] = item

    async def _retry_one_bedrock(segment: dict) -> list[dict]:
        return await _translate_chunk_via_bedrock(
            chunk=[segment],
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
            glossary_max_terms=glossary_max_terms,
            glossary_max_prompt_chars=glossary_max_prompt_chars,
            model_id=bedrock_model_id,
            region=bedrock_region,
            aws_profile=bedrock_aws_profile or None,
        )

    results_by_id = await _retry_suspicious_segments(
        results_by_id,
        retry_one=_retry_one_bedrock,
    )

    if xlsx_alias_to_representative:
        expanded_results = dict(results_by_id)
        for alias_id, representative_id in xlsx_alias_to_representative.items():
            representative = results_by_id.get(representative_id)
            if representative is None:
                continue
            alias_result = dict(representative)
            alias_result["deduped_from"] = representative_id
            expanded_results[alias_id] = alias_result
        results_by_id = expanded_results

    drafts_by_id, glossary_debug_by_id = _build_drafts_by_id(
        segments=segments,
        results_by_id=results_by_id,
        cache_hits=cache_hits,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_terms=glossary_terms,
    )
    qa_results, drafts_by_id, qa_profile = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id=drafts_by_id,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_terms=glossary_terms,
        qa_ai_enabled=qa_ai_enabled,
        bedrock_model_id=qa_ai_model_id or bedrock_model_id,
        bedrock_region=bedrock_region,
        bedrock_aws_profile=bedrock_aws_profile,
        qa_ai_uncertain_threshold=qa_ai_uncertain_threshold,
        qa_ai_batch_max_segments=qa_ai_batch_max_segments,
        qa_repair_enabled=qa_repair_enabled,
        qa_repair_max_attempts=qa_repair_max_attempts,
        qa_repair_batch_max_segments=qa_repair_batch_max_segments,
        qa_repair_model_id=bedrock_model_id,
        glossary_max_terms=glossary_max_terms,
        glossary_max_prompt_chars=glossary_max_prompt_chars,
    )

    translated_result = _build_translation_output(
        segments=segments,
        results_by_id=results_by_id,
        cache_hits=cache_hits,
        drafts_by_id=drafts_by_id,
        qa_results=qa_results,
        qa_profile=qa_profile,
        glossary_debug_by_id=glossary_debug_by_id,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_terms=glossary_terms,
    )
    if db is not None and now_iso:
        store_stats = store_tm_segments(
            db,
            segments,
            translated_result["segments"],
            source_lang,
            target_lang,
            tm_user_id,
            now_iso,
            scopes=tm_write_scopes,
        )
        tm_stats["inserted"] = int(store_stats.get("inserted", 0))
        tm_stats["updated"] = int(store_stats.get("updated", 0))
        tm_stats["skipped"] = int(store_stats.get("skipped", 0))
        tm_stats["stored"] = tm_stats["inserted"] + tm_stats["updated"]
        tm_stats["pruned"] = prune_translation_memory(db, tm_max_entries, tm_prune_batch_size)
    translated_result["tm_stats"] = dict(tm_stats)
    return translated_result
