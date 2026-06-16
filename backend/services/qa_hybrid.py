"""Hybrid QA: rule checks + optional AI adjudication + batch AI repair."""
from __future__ import annotations

import logging

from services.qa import run_first_failure, run_hard_checks, run_soft_checks
from services.qa_ai import AiQaVerdict, adjudicate_soft_failures
from services.qa_repair import (
    is_adjudicate_only_soft_rule,
    repair_glossary_from_reason,
    repair_inline_markers,
    repair_strategy_for_rule,
)
from services.qa_repair_ai import build_repair_item, repair_segments_batch, sanitize_repair_text

logger = logging.getLogger(__name__)


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
        return False, f"待人工确认（AI 置信度 {verdict.confidence:.0%}）: {verdict.reason or rule_reason}"

    ai_reason = verdict.reason or rule_reason
    if verdict.confidence < uncertain_threshold:
        return False, f"待人工确认（AI 置信度 {verdict.confidence:.0%}）: {ai_reason}"
    return False, f"AI 质检: {ai_reason}"


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
    """Evaluate QA for all segments. Returns id -> {qa_pass, qa_reason}."""
    results: dict[str, dict] = {}
    ai_queue: list[dict] = []

    for segment in segments:
        seg_id = segment["id"]
        source = segment["source_text"]
        translation = drafts_by_id.get(seg_id, "")

        hard_reason, _ = run_hard_checks(
            source=source,
            translation=translation,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
        )
        if hard_reason:
            results[seg_id] = {"qa_pass": False, "qa_reason": hard_reason}
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
                results[seg_id] = {"qa_pass": False, "qa_reason": soft_reason}
                continue
            ai_queue.append({
                "id": seg_id,
                "source": source,
                "translation": translation,
                "rule_reason": soft_reason,
            })
            results[seg_id] = {"qa_pass": False, "qa_reason": soft_reason, "_pending_ai": True}
        else:
            results[seg_id] = {"qa_pass": True, "qa_reason": None}

    use_ai = adjudicate_soft and qa_ai_enabled and bool(bedrock_model_id.strip()) and bool(ai_queue)
    if not use_ai:
        for item in results.values():
            item.pop("_pending_ai", None)
        return results

    verdicts: dict[str, AiQaVerdict] = {}
    for batch in _chunk_list(ai_queue, qa_ai_batch_max_segments):
        try:
            batch_verdicts = await adjudicate_soft_failures(
                items=batch,
                source_lang=source_lang,
                target_lang=target_lang,
                model_id=bedrock_model_id,
                region=bedrock_region,
                aws_profile=bedrock_aws_profile or None,
            )
            verdicts.update(batch_verdicts)
        except Exception as exc:
            logger.warning("AI QA batch failed, keeping rule-based soft failures: %s", exc)

    for item in ai_queue:
        seg_id = item["id"]
        if seg_id not in results:
            continue
        rule_reason = item["rule_reason"]
        verdict = verdicts.get(seg_id)
        if verdict is None:
            results[seg_id] = {"qa_pass": False, "qa_reason": rule_reason}
            continue

        qa_pass, qa_reason = _finalize_ai_verdict(verdict, rule_reason, qa_ai_uncertain_threshold)
        results[seg_id] = {"qa_pass": qa_pass, "qa_reason": qa_reason}

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
) -> tuple[dict[str, dict], dict[str, str]]:
    """Translate-then-repair: rule QA → batch AI repair → final rule QA (+ soft AI adjudication)."""
    working_drafts = dict(drafts_by_id)
    repair_model = (qa_repair_model_id or bedrock_model_id).strip()
    max_attempts = max(0, qa_repair_max_attempts)

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

        can_repair = qa_repair_enabled and attempt < max_attempts
        if not can_repair:
            break

        repair_queue: list[dict] = []
        for index, segment in enumerate(segments):
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

            repair_queue.append(
                build_repair_item(
                    segment=segment,
                    translation=translation,
                    qa_reason=reason,
                    rule_name=rule_name,
                    segments=segments,
                    index=index,
                    drafts_by_id=working_drafts,
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

            # Retry segments the model omitted one at a time (truncation / parse loss).
            missing = [item for item in batch if item["id"] not in repaired_ids]
            for item in missing:
                try:
                    single = await repair_segments_batch(
                        items=[item],
                        source_lang=source_lang,
                        target_lang=target_lang,
                        model_id=repair_model,
                        region=bedrock_region,
                        aws_profile=bedrock_aws_profile or None,
                    )
                except Exception as exc:
                    logger.warning("AI repair single-segment failed for %s: %s", item["id"], exc)
                    continue
                for seg_id, text in single.items():
                    cleaned = sanitize_repair_text(text)
                    if cleaned and cleaned != working_drafts.get(seg_id):
                        working_drafts[seg_id] = cleaned
                        batch_changed = True
            return batch_changed

        for batch in _chunk_list(ai_queue, qa_repair_batch_max_segments):
            if await _apply_repair_batch(batch):
                changed = True

        # Use all configured repair attempts even when a round makes no progress.
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
    return final_results, working_drafts
