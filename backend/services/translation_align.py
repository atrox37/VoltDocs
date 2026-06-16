"""Translation alignment helpers — detect and recover from batch mis-mapping."""
from __future__ import annotations

import re

_CIRCLED_NUM_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]$")
_STEP_NUM_RE = re.compile(r"^\d{1,3}$")
_ROMAN_RE = re.compile(r"^[IVXLCDMivxlcdm]{1,6}\.?$")


def _strip_markers(text: str) -> str:
    return re.sub(r"\*{1,3}|~~", "", text).strip()


def is_likely_misaligned(source: str, translation: str) -> bool:
    """Heuristic: short label translated as paragraph, or paragraph as label."""
    src = _strip_markers(source)
    tgt = _strip_markers(translation)
    if not src or not tgt:
        return False

    src_len = len(src)
    tgt_len = len(tgt)

    src_is_label = bool(
        _CIRCLED_NUM_RE.match(src)
        or _STEP_NUM_RE.match(src)
        or _ROMAN_RE.match(src)
    )
    tgt_is_label = bool(
        _CIRCLED_NUM_RE.match(tgt)
        or _STEP_NUM_RE.match(tgt)
        or _ROMAN_RE.match(tgt)
        or (tgt_len <= 4 and not tgt.isascii())
    )

    if src_is_label and tgt_len > 30:
        return True
    if src_len > 30 and tgt_is_label:
        return True
    if src_len <= 6 and tgt_len > 50:
        return True

    if src_len >= 15 and tgt_len >= 15:
        ratio = tgt_len / src_len
        if ratio > 15 or ratio < 0.05:
            return True

    return False


def is_untranslated_copy(
    source: str,
    translation: str,
    source_lang: str = "",
    target_lang: str = "",
) -> bool:
    """True when the model returned source text or left most content in the source language."""
    if not translation.strip():
        return False

    src = _strip_markers(source).strip()
    tgt = _strip_markers(translation).strip()
    if src and src == tgt:
        return True

    if not source_lang or not target_lang:
        return False

    def _cjk_count(text: str) -> int:
        return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")

    def _latin_count(text: str) -> int:
        return sum(1 for ch in text if ch.isascii() and ch.isalpha())

    src_cjk = _cjk_count(source)
    tgt_cjk = _cjk_count(translation)
    tgt_latin = _latin_count(translation)
    total = tgt_cjk + tgt_latin

    if source_lang.startswith("zh") and target_lang.startswith("en"):
        if src_cjk >= 3 and total > 0 and tgt_cjk / total > 0.55:
            return True

    if source_lang.startswith("en") and target_lang.startswith("zh"):
        src_latin = _latin_count(source)
        if src_latin >= 3 and total > 0 and tgt_latin / total > 0.55:
            return True

    return False


def needs_retranslation(
    source: str,
    translation: str,
    *,
    expected_id: str | None = None,
    returned_id: str | None = None,
    source_lang: str = "",
    target_lang: str = "",
) -> bool:
    if expected_id and returned_id and expected_id != returned_id:
        return True
    if not translation.strip():
        return True
    if is_untranslated_copy(source, translation, source_lang, target_lang):
        return True
    return is_likely_misaligned(source, translation)
