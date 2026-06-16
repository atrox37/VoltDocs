"""AI-assisted translation repair after QA failures."""
from __future__ import annotations

import json
import logging
import re

from services.bedrock import invoke_bedrock_text, parse_seg_xml
from services.docx.markup import clean_translation_artifacts
from services.glossary_matcher import select_terms_for_texts
from services.qa_repair import repair_strategy_for_rule

logger = logging.getLogger(__name__)

_SEG_RE = re.compile(r'<seg\s+id="([^"]+)">([\s\S]*?)</seg>')
_JSON_LINE_RE = re.compile(r"^\s*\{.*\}\s*$")
_PROMPT_TAG_RE = re.compile(
    r"</?(?:source|current_translation|corrected_translation|item|qa_failure|mandatory_glossary|prev_source|prev_translation|next_source|next_translation)(?:\s[^>]*)?>",
    re.IGNORECASE,
)
_CORRECTED_RE = re.compile(
    r"<corrected_translation>([\s\S]*?)</corrected_translation>",
    re.IGNORECASE,
)
_TRAILING_BS_RE = re.compile(r"(?:\\+\s*)+$")
_ESCAPED_MARKER_RE = re.compile(r"\\([*~])")


def _build_system_prompt(source_lang: str, target_lang: str) -> str:
    return (
        "You are a professional technical translator performing targeted translation repairs.\n"
        f"Source language: {source_lang}\n"
        f"Target language: {target_lang}\n\n"
        "Each item failed automated QA. Return a corrected translation for each id.\n\n"
        "OUTPUT FORMAT — one JSON object per line, no other text:\n"
        '{"id":"<id>","translation":"<fixed text>"}\n\n'
        "Rules:\n"
        "1. Preserve **bold**, *italic*, and ~~strikethrough~~ markers (never use backslash escapes)\n"
        "2. Use mandatory glossary terms exactly when provided\n"
        "3. For empty or untranslated text: produce a complete target-language translation\n"
        "4. Circled numbers (①②③): keep short — translate the label only, never leave empty\n"
        "5. Never echo SOURCE/CURRENT fields; never wrap output in XML tags\n"
        "6. Keep numbers, units, and model codes accurate"
    )


def _build_user_message(items: list[dict]) -> str:
    blocks: list[str] = []
    for item in items:
        strategy = item.get("strategy") or repair_strategy_for_rule(item.get("rule_name", ""))
        glossary_lines = [
            f"  {term['source']} -> {term['target']}"
            for term in item.get("glossary", [])
            if term.get("source") and term.get("target")
        ]
        glossary_block = ""
        if glossary_lines:
            glossary_block = "GLOSSARY (mandatory):\n" + "\n".join(glossary_lines) + "\n"

        blocks.append(
            f"--- id={item['id']} strategy={strategy} ---\n"
            f"QA_FAILURE: {item['qa_reason']}\n"
            f"SOURCE: {item['source']}\n"
            f"CURRENT: {item['translation'] or '(empty)'}\n"
            f"{glossary_block}"
        )
    return (
        "Repair each item. Return one JSON line per id with the fixed translation only.\n\n"
        + "\n".join(blocks)
    )


def sanitize_repair_text(text: str) -> str:
    """Strip prompt leakage, XML artifacts, and spurious backslashes from model output."""
    if not text:
        return ""

    had_prompt_tags = bool(_PROMPT_TAG_RE.search(text) or _CORRECTED_RE.search(text))
    result = text.strip()
    corrected = _CORRECTED_RE.search(result)
    if corrected:
        result = corrected.group(1).strip()
    elif had_prompt_tags:
        return ""

    result = _PROMPT_TAG_RE.sub("", result)
    result = re.sub(r"<bold>(.*?)</bold>", r"**\1**", result, flags=re.IGNORECASE)
    result = re.sub(r"<italic>(.*?)</italic>", r"*\1*", result, flags=re.IGNORECASE)
    result = _ESCAPED_MARKER_RE.sub(r"\1", result)
    result = result.replace("\\n", "\n").replace("\\t", "\t")
    result = _TRAILING_BS_RE.sub("", result).strip()
    result = re.sub(r"\\+$", "", result).strip()

    if _PROMPT_TAG_RE.search(result) or "<source>" in result.lower():
        return ""
    return clean_translation_artifacts(result)


def _parse_json_lines(raw_text: str, expected_ids: set[str]) -> dict[str, str]:
    results: dict[str, str] = {}
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or not _JSON_LINE_RE.match(line):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        seg_id = str(item.get("id", "")).strip()
        if seg_id not in expected_ids:
            continue
        translation = sanitize_repair_text(str(item.get("translation", "")))
        if translation:
            results[seg_id] = translation
    return results


def _parse_segments(raw_text: str, expected_ids: set[str]) -> dict[str, str]:
    results = _parse_json_lines(raw_text, expected_ids)
    if results:
        return results

    for item in parse_seg_xml(raw_text):
        seg_id = item["id"]
        if seg_id in expected_ids:
            cleaned = sanitize_repair_text(item["translation"])
            if cleaned:
                results[seg_id] = cleaned

    if results:
        return results

    for match in _SEG_RE.finditer(raw_text):
        seg_id = match.group(1)
        if seg_id in expected_ids:
            cleaned = sanitize_repair_text(match.group(2))
            if cleaned:
                results[seg_id] = cleaned

    if not results and expected_ids:
        logger.warning("Repair response produced no usable segments: %s", raw_text[:200])
    return results


async def repair_segments_batch(
    items: list[dict],
    source_lang: str,
    target_lang: str,
    model_id: str,
    region: str,
    aws_profile: str | None = None,
) -> dict[str, str]:
    if not items:
        return {}

    expected_ids = {item["id"] for item in items}
    max_tokens = min(8192, 400 * len(items) + 512)
    raw = await invoke_bedrock_text(
        system_prompt=_build_system_prompt(source_lang, target_lang),
        user_message=_build_user_message(items),
        model_id=model_id,
        region=region,
        aws_profile=aws_profile,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return _parse_segments(raw, expected_ids)


def build_repair_item(
    segment: dict,
    translation: str,
    qa_reason: str,
    rule_name: str,
    segments: list[dict],
    index: int,
    drafts_by_id: dict[str, str],
    glossary_terms: list[dict] | None,
    glossary_max_terms: int,
    glossary_max_prompt_chars: int,
) -> dict:
    prev_seg = segments[index - 1] if index > 0 else None
    next_seg = segments[index + 1] if index + 1 < len(segments) else None
    matched_glossary = []
    if glossary_terms:
        matched_glossary = select_terms_for_texts(
            glossary_terms,
            [segment["source_text"]],
            glossary_max_terms,
            glossary_max_prompt_chars,
        )
    return {
        "id": segment["id"],
        "source": segment["source_text"],
        "translation": translation,
        "qa_reason": qa_reason,
        "rule_name": rule_name,
        "strategy": repair_strategy_for_rule(rule_name),
        "glossary": matched_glossary,
        "prev_source": prev_seg["source_text"] if prev_seg else None,
        "prev_translation": drafts_by_id.get(prev_seg["id"]) if prev_seg else None,
        "next_source": next_seg["source_text"] if next_seg else None,
        "next_translation": drafts_by_id.get(next_seg["id"]) if next_seg else None,
    }
