"""Translation QA rules.

Each rule is a function with signature:
    (source: str, translation: str, **kwargs) -> str | None

Returns a human-readable failure reason, or None if the check passes.
``run_all_checks`` runs every rule and returns the first failure found
(rules are ordered from most critical to least critical).
"""
from __future__ import annotations

import re


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_numbers(text: str) -> list[str]:
    """Return all distinct numbers that are meaningful (≥2 digits, or decimal)."""
    found = re.findall(r"\d+(?:\.\d+)?", text)
    return sorted({n for n in found if len(n) >= 2 or "." in n})


def _count_cjk(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _count_latin(text: str) -> int:
    return sum(1 for ch in text if ch.isascii() and ch.isalpha())


# ── Rule 1: Empty translation ─────────────────────────────────────────────────

def check_empty(source: str, translation: str, **_) -> str | None:
    if not translation.strip():
        return "译文为空"
    return None


# ── Rule 2: Number consistency ────────────────────────────────────────────────

def check_numbers(source: str, translation: str, **_) -> str | None:
    """All significant numbers in the source must appear in the translation."""
    numbers = _extract_numbers(source)
    missing = [n for n in numbers if n not in translation]
    if missing:
        return f"数字不一致，译文缺少: {', '.join(missing)}"
    return None


# ── Rule 3: Inline formatting markers ────────────────────────────────────────

def check_inline_markers(source: str, translation: str, **_) -> str | None:
    """Bold / italic / strikethrough markers present in source must survive."""
    for marker, name in (("**", "粗体"), ("~~", "删除线")):
        src_count = source.count(marker)
        tgt_count = translation.count(marker)
        # Must have same count (markers come in pairs)
        if src_count and tgt_count != src_count:
            return f"格式标记丢失或多余: {marker}（原文 {src_count} 个，译文 {tgt_count} 个）"

    # Single-asterisk italic: count occurrences that are NOT part of **
    def _italic_count(text: str) -> int:
        # Replace ** first to not double-count
        cleaned = text.replace("**", "")
        return cleaned.count("*")

    src_italic = _italic_count(source)
    tgt_italic = _italic_count(translation)
    if src_italic and tgt_italic != src_italic:
        return f"格式标记丢失或多余: *（原文 {src_italic} 个，译文 {tgt_italic} 个）"

    return None


# ── Rule 4: Length ratio ──────────────────────────────────────────────────────

# Thresholds are intentionally loose to avoid false positives.
# zh→en expansions of 3× are normal for short technical terms.
# en→zh contractions of 10× are normal for dense paragraphs.
_MIN_RATIO = 0.08   # translation must be at least 8% of source length
_MAX_RATIO = 20.0   # translation must not be more than 20× source length


def check_length_ratio(source: str, translation: str, **_) -> str | None:
    """Catch wildly disproportionate translations (runaway output or truncation)."""
    src_len = len(source.strip())
    tgt_len = len(translation.strip())
    if src_len == 0:
        return None
    ratio = tgt_len / src_len
    if ratio < _MIN_RATIO:
        return f"译文过短（原文 {src_len} 字符，译文 {tgt_len} 字符，比例 {ratio:.2f}）"
    if ratio > _MAX_RATIO:
        return f"译文过长（原文 {src_len} 字符，译文 {tgt_len} 字符，比例 {ratio:.1f}×）"
    return None


# ── Rule 5: Source language leakage ──────────────────────────────────────────

def check_language_leakage(source: str, translation: str, source_lang: str = "", target_lang: str = "", **_) -> str | None:
    """Detect when the output language looks wrong.

    Only fires when translation direction is clear (zh→en or en→zh).
    We avoid false positives on mixed-language technical content (product codes,
    acronyms, etc.) by requiring a strong imbalance before flagging.
    """
    if not source_lang or not target_lang:
        return None

    tgt_cjk = _count_cjk(translation)
    tgt_latin = _count_latin(translation)
    total = tgt_cjk + tgt_latin
    if total == 0:
        return None

    cjk_ratio = tgt_cjk / total
    latin_ratio = tgt_latin / total

    if source_lang.startswith("zh") and target_lang.startswith("en"):
        # Expect mostly Latin output; flag if > 60% CJK
        if cjk_ratio > 0.60:
            return "疑似未翻译（目标语言应为英文，但译文大部分仍为中文）"

    if source_lang.startswith("en") and target_lang.startswith("zh"):
        # Expect mostly CJK output; flag if > 60% Latin
        if latin_ratio > 0.60:
            return "疑似未翻译（目标语言应为中文，但译文大部分仍为英文）"

    return None


# ── Rule 6: Required terminology ─────────────────────────────────────────────

def check_required_terms(
    source: str,
    translation: str,
    source_lang: str = "",
    target_lang: str = "",
    glossary_terms: list[dict] | None = None,
    **_,
) -> str | None:
    """Verify that mandatory glossary terms are used in the translation.

    Only checks terms where ``required`` is truthy AND the source term
    actually appears in the source text.
    """
    if not glossary_terms:
        return None

    is_zh_to_en = source_lang.startswith("zh") and target_lang.startswith("en")
    missing_terms: list[str] = []

    for term in glossary_terms:
        if not term.get("required"):
            continue
        src_term: str = term.get("source", "")
        tgt_term: str = term.get("target", "")
        if not src_term or not tgt_term:
            continue

        # Reverse mapping for en→zh
        if not is_zh_to_en:
            src_term, tgt_term = tgt_term, src_term

        if src_term.lower() in source.lower() and tgt_term.lower() not in translation.lower():
            missing_terms.append(f"{src_term} → {tgt_term}")

    if missing_terms:
        return f"必须使用的术语未出现在译文中: {'; '.join(missing_terms)}"
    return None


# ── Rule 7: Punctuation sanity ────────────────────────────────────────────────

def check_punctuation(source: str, translation: str, target_lang: str = "", **_) -> str | None:
    """Catch obvious punctuation mismatch for zh↔en translations."""
    if not target_lang:
        return None

    tgt = translation.strip()

    # zh target: ends with ASCII period/question mark when it should use fullwidth
    if target_lang.startswith("zh"):
        if len(tgt) > 5 and tgt[-1] in ".?!":
            src_cjk = _count_cjk(source)
            # Only flag when source has substantial Chinese content (>= 5 CJK chars)
            # to avoid false positives on short technical terms like "太阳能"
            if src_cjk >= 5:
                return "中文译文以英文标点结尾，建议使用全角标点"

    # en target: ends with Chinese fullwidth punctuation
    if target_lang.startswith("en"):
        if tgt and tgt[-1] in "。！？；：":
            return "英文译文以中文标点结尾"

    return None


# ── Runner ────────────────────────────────────────────────────────────────────

# Rules ordered from most critical to least; first failure is reported.
_RULES = [
    check_empty,
    check_numbers,
    check_inline_markers,
    check_length_ratio,
    check_language_leakage,
    check_required_terms,
    check_punctuation,
]


def run_all_checks(
    source: str,
    translation: str,
    source_lang: str = "",
    target_lang: str = "",
    glossary_terms: list[dict] | None = None,
) -> str | None:
    """Run all QA rules and return the first failure reason, or None if all pass."""
    kwargs = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "glossary_terms": glossary_terms,
    }
    for rule in _RULES:
        reason = rule(source, translation, **kwargs)
        if reason:
            return reason
    return None
