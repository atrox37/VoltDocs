"""AI-assisted translation QA — adjudicates soft rule failures via Bedrock."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from services.bedrock import invoke_bedrock_text

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


@dataclass(frozen=True)
class AiQaVerdict:
    segment_id: str
    pass_: bool
    confidence: float
    reason: str | None = None


def _build_system_prompt(source_lang: str, target_lang: str) -> str:
    return (
        "You are a professional translation quality reviewer for technical documentation.\n"
        f"Source language: {source_lang}\n"
        f"Target language: {target_lang}\n\n"
        "Each item was flagged by an automated rule. Your job is to decide whether the "
        "translation is actually acceptable despite the rule warning.\n\n"
        "Treat these as EQUIVALENT (should PASS):\n"
        "- Number formatting: 1000 = 1,000 = 1 000\n"
        "- Month expressions: 11月 = November = Nov\n"
        "- Minor punctuation localization when meaning is preserved\n"
        "- Mixed-language segments that are correct for technical labels, model codes, or acronyms\n"
        "- Length differences that are normal for the language pair\n\n"
        "Treat these as REAL problems (should FAIL):\n"
        "- Missing, added, or wrong numbers, dates, units, or amounts\n"
        "- Untranslated prose that should be in the target language\n"
        "- Omitted or materially changed meaning\n\n"
        "Respond with ONLY a JSON array. No markdown, no explanation outside JSON.\n"
        "Each element must have:\n"
        '  {"id": "<segment id>", "pass": true|false, "confidence": 0.0-1.0, "reason": "<short Chinese explanation or null>"}\n'
        "Use concise Simplified Chinese for non-null reason fields."
    )


def _build_user_message(items: list[dict]) -> str:
    blocks: list[str] = []
    for item in items:
        blocks.append(
            f'<item id="{item["id"]}">\n'
            f"<rule_warning>{item['rule_reason']}</rule_warning>\n"
            f"<source>{item['source']}</source>\n"
            f"<translation>{item['translation']}</translation>\n"
            f"</item>"
        )
    return (
        "Review the following flagged translation segments.\n"
        "Return a JSON array with one verdict per id.\n\n"
        + "\n".join(blocks)
    )


def _parse_verdicts(raw_text: str, expected_ids: set[str]) -> dict[str, AiQaVerdict]:
    text = raw_text.strip()
    block_match = _JSON_BLOCK_RE.search(text)
    if block_match:
        text = block_match.group(1).strip()

    # Allow a bare array or {"verdicts": [...]}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        array_match = re.search(r"\[[\s\S]*\]", text)
        if not array_match:
            raise ValueError(f"Could not parse AI QA JSON: {raw_text[:300]}")
        parsed = json.loads(array_match.group(0))

    if isinstance(parsed, dict):
        parsed = parsed.get("verdicts") or parsed.get("results") or []

    if not isinstance(parsed, list):
        raise ValueError("AI QA response is not a JSON array")

    verdicts: dict[str, AiQaVerdict] = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        seg_id = str(entry.get("id", "")).strip()
        if not seg_id or seg_id not in expected_ids:
            continue
        confidence = float(entry.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        reason = entry.get("reason")
        if reason is not None:
            reason = str(reason).strip() or None
        verdicts[seg_id] = AiQaVerdict(
            segment_id=seg_id,
            pass_=bool(entry.get("pass", False)),
            confidence=confidence,
            reason=reason,
        )
    return verdicts


async def adjudicate_soft_failures(
    items: list[dict],
    source_lang: str,
    target_lang: str,
    model_id: str,
    region: str,
    aws_profile: str | None = None,
) -> dict[str, AiQaVerdict]:
    """Ask the LLM to review segments that failed soft QA rules.

    Args:
        items: [{"id", "source", "translation", "rule_reason"}, ...]
    """
    if not items:
        return {}

    expected_ids = {item["id"] for item in items}
    raw = await invoke_bedrock_text(
        system_prompt=_build_system_prompt(source_lang, target_lang),
        user_message=_build_user_message(items),
        model_id=model_id,
        region=region,
        aws_profile=aws_profile,
        max_tokens=4096,
        temperature=0.0,
    )
    return _parse_verdicts(raw, expected_ids)
