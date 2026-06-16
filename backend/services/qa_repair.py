"""Deterministic QA repairs — no LLM."""
from __future__ import annotations

import re

_MARKER_STRIP = re.compile(r"\*{1,3}|~~")
_GLOSSARY_PAIR_RE = re.compile(r"([^→;]+?) → ([^→;]+?)(?:;|$)")


# Soft rules that only need AI adjudication (not auto-repair) — e.g. 1000 vs 1,000.
ADJUDICATE_ONLY_SOFT_RULES = frozenset({
    "check_numbers",
    "check_length_ratio",
    "check_punctuation",
})


def _parse_glossary_pairs(qa_reason: str) -> list[tuple[str, str]]:
    if "术语未按术语表翻译" not in (qa_reason or ""):
        return []
    payload = qa_reason.split(":", 1)[-1]
    pairs: list[tuple[str, str]] = []
    for src_term, tgt_term in _GLOSSARY_PAIR_RE.findall(payload):
        src_term = src_term.strip()
        tgt_term = tgt_term.strip()
        if src_term and tgt_term:
            pairs.append((src_term, tgt_term))
    return pairs


def repair_glossary_from_reason(source: str, translation: str, qa_reason: str) -> str:
    """Best-effort rule-based glossary fix before AI repair (e.g. List of Materials → Bill of Materials)."""
    result = translation or ""
    for src_term, tgt_term in _parse_glossary_pairs(qa_reason):
        if src_term not in source:
            continue
        if tgt_term.lower() in result.lower():
            continue

        tgt_words = tgt_term.split()
        if len(tgt_words) >= 2:
            last = re.escape(tgt_words[-1].rstrip("s"))
            pattern = rf"\b(?:\w+\s+){{0,5}}{last}s?\b"
            for match in re.finditer(pattern, result, re.IGNORECASE):
                phrase = match.group(0)
                if tgt_term.lower() in phrase.lower():
                    continue
                result = result[: match.start()] + tgt_term + result[match.end() :]
                break

        # Common zh→en mistranslations for short technical terms
        if src_term == "地脚" and tgt_term == "Base Foot":
            result = re.sub(r"\bbase\s+plate\b", "Base Foot", result, count=1, flags=re.IGNORECASE)
        if src_term == "装配图" and "Assembly Drawing" in tgt_term:
            result = re.sub(
                r"\b(?:sample\s+)?assembly\s+pictures?\b",
                "Assembly Drawing",
                result,
                count=1,
                flags=re.IGNORECASE,
            )
    return result


def repair_inline_markers(source: str, translation: str) -> str:
    """Wrap literal tokens in the translation when the source bolded the same token."""
    result = translation

    for pattern, wrapper in (
        (r"\*\*([^*]+)\*\*", ("**", "**")),
        (r"~~([^~]+)~~", ("~~", "~~")),
    ):
        for match in re.finditer(pattern, source):
            inner = match.group(1).strip()
            if not inner:
                continue
            plain = _MARKER_STRIP.sub("", inner).strip()
            for token in (inner, plain):
                if not token:
                    continue
                wrapped = f"{wrapper[0]}{token}{wrapper[1]}"
                if token in result and wrapped not in result:
                    result = result.replace(token, wrapped, 1)
                    break

    for match in re.finditer(r"(?<!\*)\*([^*]+)\*(?!\*)", source):
        inner = match.group(1).strip()
        if not inner:
            continue
        plain = _MARKER_STRIP.sub("", inner).strip()
        for token in (inner, plain):
            if not token:
                continue
            wrapped = f"*{token}*"
            if token in result and wrapped not in result:
                result = result.replace(token, wrapped, 1)
                break

    return result


def is_adjudicate_only_soft_rule(rule_name: str) -> bool:
    return rule_name in ADJUDICATE_ONLY_SOFT_RULES


def repair_strategy_for_rule(rule_name: str) -> str:
    """Return repair strategy: markers | glossary | retranslate | repair."""
    if rule_name in (
        "check_empty",
        "check_language_leakage",
        "check_segment_alignment",
        "check_markup_artifacts",
    ):
        return "retranslate"
    if rule_name == "check_inline_markers":
        return "markers"
    if rule_name == "check_required_terms":
        return "glossary"
    return "repair"
