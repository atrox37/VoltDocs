"""Hybrid QA: rule checks + optional AI adjudication + batch AI repair."""
from __future__ import annotations

import asyncio
from collections import Counter
import logging

from services.qa import failure_type_for_rule, run_first_failure, run_hard_checks, run_soft_checks
from services.qa_ai import AiQaVerdict, adjudicate_soft_failures
from services.qa_repair import (
    is_adjudicate_only_soft_rule,
    repair_glossary_from_reason,
    repair_inline_markers,
    repair_strategy_for_rule,
)
from services.qa_repair_ai import build_repair_item, repair_segments_batch, sanitize_repair_text
from services.translation_align import is_translation_required

logger = logging.getLogger(__name__)
_QA_DEBUG_HISTORY_LIMIT = 2
_QA_BATCH_CONCURRENCY = 4


async def _run_batches_limited(
    batches: list[list[dict]],
    worker,
    *,
    concurrency: int = _QA_BATCH_CONCURRENCY,
):
    if not batches:
        return []

    semaphore = asyncio.Semaphore(max(1, min(concurrency, len(batches))))

    async def _run(batch: list[dict]):
        async with semaphore:
            return await worker(batch)

    return await asyncio.gather(*[_run(batch) for batch in batches])


def _chunk_list(items: list[dict], size: int) -> list[list[dict]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _finalize_ai_verdict(
    verdict: AiQaVerdict,
    rule_reason: str,
    uncertain_threshold: float,
) -> tuple[bool, str | None]:
    if verdict.pass_:
        if verdict.confidence >= uncertain_threshold:
            return True, None
        return False, f"Manual confirmation required (AI confidence {verdict.confidence:.0%}): {verdict.reason or rule_reason}"

    ai_reason = verdict.reason or rule_reason
    if verdict.confidence < uncertain_threshold:
        return False, f"Manual confirmation required (AI confidence {verdict.confidence:.0%}): {ai_reason}"
    return False, f"AI QA: {ai_reason}"


def _round_summary(round_index: int, results: dict[str, dict]) -> dict:
    failed_items = [item for item in results.values() if not item.get("qa_pass")]
    rule_counts = Counter(item.get("qa_rule_name") for item in failed_items if item.get("qa_rule_name"))
    failure_type_counts = Counter(item.get("qa_failure_type") for item in failed_items if item.get("qa_failure_type"))
    top_rule_name = rule_counts.most_common(1)[0][0] if rule_counts else None
    return {
        "round": round_index,
        "failedSegments": len(failed_items),
        "ruleCounts": dict(rule_counts),
        "failureTypes": dict(failure_type_counts),
        "topRuleName": top_rule_name,
    }


def _record_segment_history(
    segment_profiles: dict[str, dict],
    *,
    round_index: int,
    seg_id: str,
    result: dict,
    translation: str,
) -> None:
    profile = segment_profiles.setdefault(
        seg_id,
        {
            "history": [],
            "stoppedEarly": False,
            "stoppedReason": None,
        },
    )
    profile["history"].append(
        {
            "round": round_index,
            "qaPass": bool(result.get("qa_pass")),
            "ruleName": result.get("qa_rule_name"),
            "failureType": result.get("qa_failure_type"),
            "reason": result.get("qa_reason"),
            "translation": translation,
        }
    )


def _should_stop_repair(segment_profile: dict | None) -> tuple[bool, str | None]:
    if not segment_profile:
        return False, None
    failed_history = [item for item in segment_profile.get("history", []) if not item.get("qaPass")]
    if len(failed_history) < 2:
        return False, None
    latest = failed_history[-1]
    previous = failed_history[-2]
    if latest.get("ruleName") != previous.get("ruleName"):
        return False, None
    if latest.get("failureType") != previous.get("failureType"):
        return False, None
    no_improvement = (
        latest.get("translation") == previous.get("translation")
        or latest.get("reason") == previous.get("reason")
    )
    if not no_improvement:
        return False, None
    return True, "Repeated same QA rule without improvement across consecutive rounds"


def _build_qa_profile(round_summaries: list[dict], segment_profiles: dict[str, dict]) -> dict:
    all_rule_counts = Counter()
    all_failure_type_counts = Counter()
    stopped_segments = 0
    for round_summary in round_summaries:
        all_rule_counts.update(round_summary.get("ruleCounts") or {})
        all_failure_type_counts.update(round_summary.get("failureTypes") or {})
    for profile in segment_profiles.values():
        if profile.get("stoppedEarly"):
            stopped_segments += 1
    return {
        "rounds": round_summaries,
        "summary": {
            "roundCount": len(round_summaries),
            "mostCommonRuleName": all_rule_counts.most_common(1)[0][0] if all_rule_counts else None,
            "ruleCounts": dict(all_rule_counts),
            "failureTypes": dict(all_failure_type_counts),
            "stoppedSegments": stopped_segments,
        },
    }


async def evaluate_segments_qa(
    segments: list[dict],
    drafts_by_id: dict[str, str],
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None = None,
    *,
    qa_ai_enabled: bool = True,
    bedrock_model_id: str = "",
    bedrock_region: str = "us-east-1",
    bedrock_aws_profile: str = "",
    qa_ai_uncertain_threshold: float = 0.75,
    qa_ai_batch_max_segments: int = 50,
    adjudicate_soft: bool = True,
) -> dict[str, dict]:
    """Evaluate QA for all segments. Returns id -> QA result metadata."""
    results: dict[str, dict] = {}
    ai_queue: list[dict] = []

    for segment in segments:
        seg_id = segment["id"]
        source = segment["source_text"]
        translation = drafts_by_id.get(seg_id, "")
        if (
            not is_translation_required(source, source_lang=source_lang, target_lang=target_lang)
            and source.strip()
            and source.strip() == translation.strip()
        ):
            results[seg_id] = {
                "qa_pass": True,
                "qa_reason": None,
                "qa_rule_name": None,
                "qa_failure_type": None,
            }
            continue
        hard_reason, hard_rule = run_hard_checks(
            source=source,
            translation=translation,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
        )
        if hard_reason:
            results[seg_id] = {
                "qa_pass": False,
                "qa_reason": hard_reason,
                "qa_rule_name": hard_rule,
                "qa_failure_type": failure_type_for_rule(hard_rule),
            }
            continue

        soft_reason, soft_rule = run_soft_checks(
            source=source,
            translation=translation,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
        )
        if soft_reason:
            if not adjudicate_soft or not is_adjudicate_only_soft_rule(soft_rule or ""):
                results[seg_id] = {
                    "qa_pass": False,
                    "qa_reason": soft_reason,
                    "qa_rule_name": soft_rule,
                    "qa_failure_type": failure_type_for_rule(soft_rule),
                }
                continue
            ai_queue.append(
                {
                    "id": seg_id,
                    "source": source,
                    "translation": translation,
                    "rule_reason": soft_reason,
                    "rule_name": soft_rule,
                }
            )
            results[seg_id] = {
                "qa_pass": False,
                "qa_reason": soft_reason,
                "qa_rule_name": soft_rule,
                "qa_failure_type": failure_type_for_rule(soft_rule),
                "_pending_ai": True,
            }
        else:
            results[seg_id] = {
                "qa_pass": True,
                "qa_reason": None,
                "qa_rule_name": None,
                "qa_failure_type": None,
            }

    use_ai = adjudicate_soft and qa_ai_enabled and bool(bedrock_model_id.strip()) and bool(ai_queue)
    if not use_ai:
        for item in results.values():
            item.pop("_pending_ai", None)
        return results

    async def _adjudicate_batch(batch: list[dict]) -> dict[str, AiQaVerdict]:
        try:
            return await adjudicate_soft_failures(
                items=batch,
                source_lang=source_lang,
                target_lang=target_lang,
                model_id=bedrock_model_id,
                region=bedrock_region,
                aws_profile=bedrock_aws_profile or None,
            )
        except Exception as exc:
            logger.warning("AI QA batch failed, keeping rule-based soft failures: %s", exc)
            return {}

    verdicts: dict[str, AiQaVerdict] = {}
    for batch_verdicts in await _run_batches_limited(
        _chunk_list(ai_queue, qa_ai_batch_max_segments),
        _adjudicate_batch,
    ):
        verdicts.update(batch_verdicts)

    for item in ai_queue:
        seg_id = item["id"]
        if seg_id not in results:
            continue
        rule_reason = item["rule_reason"]
        rule_name = item["rule_name"]
        verdict = verdicts.get(seg_id)
        if verdict is None:
            results[seg_id] = {
                "qa_pass": False,
                "qa_reason": rule_reason,
                "qa_rule_name": rule_name,
                "qa_failure_type": failure_type_for_rule(rule_name),
            }
            continue

        qa_pass, qa_reason = _finalize_ai_verdict(verdict, rule_reason, qa_ai_uncertain_threshold)
        results[seg_id] = {
            "qa_pass": qa_pass,
            "qa_reason": qa_reason,
            "qa_rule_name": None if qa_pass else rule_name,
            "qa_failure_type": None if qa_pass else failure_type_for_rule(rule_name),
        }

    for item in results.values():
        item.pop("_pending_ai", None)
    return results


async def evaluate_segments_qa_with_repair(
    segments: list[dict],
    drafts_by_id: dict[str, str],
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None = None,
    *,
    qa_ai_enabled: bool = True,
    bedrock_model_id: str = "",
    bedrock_region: str = "us-east-1",
    bedrock_aws_profile: str = "",
    qa_ai_uncertain_threshold: float = 0.75,
    qa_ai_batch_max_segments: int = 40,
    qa_repair_enabled: bool = True,
    qa_repair_max_attempts: int = 1,
    qa_repair_batch_max_segments: int = 40,
    qa_repair_model_id: str = "",
    glossary_max_terms: int = 100,
    glossary_max_prompt_chars: int = 12000,
) -> tuple[dict[str, dict], dict[str, str], dict]:
    """Translate-then-repair with per-round failure profiling and stop conditions."""
    working_drafts = dict(drafts_by_id)
    repair_model = (qa_repair_model_id or bedrock_model_id).strip()
    max_attempts = max(0, qa_repair_max_attempts)
    round_summaries: list[dict] = []
    segment_profiles: dict[str, dict] = {}

    for attempt in range(max_attempts + 1):
        results = await evaluate_segments_qa(
            segments=segments,
            drafts_by_id=working_drafts,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
            qa_ai_enabled=qa_ai_enabled,
            bedrock_model_id=bedrock_model_id,
            bedrock_region=bedrock_region,
            bedrock_aws_profile=bedrock_aws_profile,
            qa_ai_uncertain_threshold=qa_ai_uncertain_threshold,
            qa_ai_batch_max_segments=qa_ai_batch_max_segments,
            adjudicate_soft=False,
        )
        round_summaries.append(_round_summary(attempt, results))
        for segment in segments:
            seg_id = segment["id"]
            _record_segment_history(
                segment_profiles,
                round_index=attempt,
                seg_id=seg_id,
                result=results.get(
                    seg_id,
                    {
                        "qa_pass": True,
                        "qa_reason": None,
                        "qa_rule_name": None,
                        "qa_failure_type": None,
                    },
                ),
                translation=working_drafts.get(seg_id, ""),
            )

        can_repair = qa_repair_enabled and attempt < max_attempts
        if not can_repair:
            break

        repair_queue: list[dict] = []
        for segment in segments:
            seg_id = segment["id"]
            if results.get(seg_id, {}).get("qa_pass"):
                continue

            translation = working_drafts.get(seg_id, "")
            reason, rule_name = run_first_failure(
                source=segment["source_text"],
                translation=translation,
                source_lang=source_lang,
                target_lang=target_lang,
                glossary_terms=glossary_terms,
            )
            if not reason or not rule_name:
                continue
            if is_adjudicate_only_soft_rule(rule_name):
                continue

            stop_repair, stop_reason = _should_stop_repair(segment_profiles.get(seg_id))
            if stop_repair:
                profile = segment_profiles.setdefault(seg_id, {"history": [], "stoppedEarly": False, "stoppedReason": None})
                profile["stoppedEarly"] = True
                profile["stoppedReason"] = stop_reason
                continue

            repair_queue.append(
                build_repair_item(
                    segment=segment,
                    translation=translation,
                    qa_reason=reason,
                    rule_name=rule_name,
                    glossary_terms=glossary_terms,
                    glossary_max_terms=glossary_max_terms,
                    glossary_max_prompt_chars=glossary_max_prompt_chars,
                )
            )

        if not repair_queue:
            break

        changed = False
        ai_queue: list[dict] = []
        for item in repair_queue:
            if repair_strategy_for_rule(item["rule_name"]) == "markers":
                fixed = repair_inline_markers(item["source"], working_drafts[item["id"]])
                if fixed != working_drafts[item["id"]]:
                    working_drafts[item["id"]] = fixed
                    changed = True
                    continue
            if item["rule_name"] == "check_required_terms":
                fixed = repair_glossary_from_reason(
                    item["source"],
                    working_drafts[item["id"]],
                    item["qa_reason"],
                )
                if fixed != working_drafts[item["id"]]:
                    working_drafts[item["id"]] = fixed
                    changed = True
                    continue
            ai_queue.append(item)

        async def _apply_repair_batch(batch: list[dict]) -> bool:
            if not batch or not repair_model:
                return False
            batch_changed = False
            try:
                repaired = await repair_segments_batch(
                    items=batch,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    model_id=repair_model,
                    region=bedrock_region,
                    aws_profile=bedrock_aws_profile or None,
                )
            except Exception as exc:
                logger.warning("AI repair batch failed: %s", exc)
                return False

            repaired_ids = set(repaired)
            for seg_id, text in repaired.items():
                cleaned = sanitize_repair_text(text)
                if cleaned and cleaned != working_drafts.get(seg_id):
                    working_drafts[seg_id] = cleaned
                    batch_changed = True

            missing = [item for item in batch if item["id"] not in repaired_ids]
            if missing:
                async def _repair_single(item: dict) -> dict[str, str]:
                    try:
                        return await repair_segments_batch(
                            items=[item],
                            source_lang=source_lang,
                            target_lang=target_lang,
                            model_id=repair_model,
                            region=bedrock_region,
                            aws_profile=bedrock_aws_profile or None,
                        )
                    except Exception as exc:
                        logger.warning("AI repair single-segment failed for %s: %s", item["id"], exc)
                        return {}

                for single in await _run_batches_limited(
                    [[item] for item in missing],
                    lambda batch: _repair_single(batch[0]),
                ):
                    for seg_id, text in single.items():
                        cleaned = sanitize_repair_text(text)
                        if cleaned and cleaned != working_drafts.get(seg_id):
                            working_drafts[seg_id] = cleaned
                            batch_changed = True
            return batch_changed

        repair_batches = _chunk_list(ai_queue, qa_repair_batch_max_segments)

        for batch_changed in await _run_batches_limited(repair_batches, _apply_repair_batch):
            if batch_changed:
                changed = True

        if not changed:
            logger.debug("QA repair attempt %d made no changes (%d items queued)", attempt + 1, len(repair_queue))

    final_results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id=working_drafts,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_terms=glossary_terms,
        qa_ai_enabled=qa_ai_enabled,
        bedrock_model_id=bedrock_model_id,
        bedrock_region=bedrock_region,
        bedrock_aws_profile=bedrock_aws_profile,
        qa_ai_uncertain_threshold=qa_ai_uncertain_threshold,
        qa_ai_batch_max_segments=qa_ai_batch_max_segments,
        adjudicate_soft=True,
    )
    final_round_index = len(round_summaries)
    round_summaries.append(_round_summary(final_round_index, final_results))
    for segment in segments:
        seg_id = segment["id"]
        _record_segment_history(
            segment_profiles,
            round_index=final_round_index,
            seg_id=seg_id,
            result=final_results.get(
                seg_id,
                {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                },
            ),
            translation=working_drafts.get(seg_id, ""),
        )
        profile = segment_profiles.get(seg_id, {})
        final_results.setdefault(seg_id, {})
        final_results[seg_id]["qa_debug"] = {
            "history": (profile.get("history", []) or [])[-_QA_DEBUG_HISTORY_LIMIT:],
            "stoppedEarly": bool(profile.get("stoppedEarly")),
            "stoppedReason": profile.get("stoppedReason"),
            "finalRuleName": final_results[seg_id].get("qa_rule_name"),
            "finalFailureType": final_results[seg_id].get("qa_failure_type"),
        }

    return final_results, working_drafts, _build_qa_profile(round_summaries, segment_profiles)
