"""Translation alignment helpers to detect and recover from batch mis-mapping."""
from __future__ import annotations

from difflib import SequenceMatcher
import re

_CIRCLED_NUM_RE = re.compile(r"^[①-⑩]$")
_STEP_NUM_RE = re.compile(r"^\d{1,3}$")
_ROMAN_RE = re.compile(r"^[IVXLCDMivxlcdm]{1,6}\.?$")
_CODE_TOKEN_RE = re.compile(
    r"^(?:[A-Za-z]{1,6}\d+(?:\.\d+){0,4}|[A-Za-z]{1,6}-\d+(?:\.\d+){0,4}|[A-Za-z]\d{1,4})$"
)
_UNIVERSAL_ALLOWED_RE = re.compile(r"^[0-9A-Za-z\s,./×xX*+\-–—≤≥<>=%(){}\[\]:;_²³°'\"µμΩ]+$")
_UNIVERSAL_UNIT_TOKENS = {
    "a", "ma", "ka",
    "v", "mv", "kv", "vdc", "vac", "dc", "ac",
    "w", "kw", "mw", "wh", "kwh",
    "hz", "khz", "mhz", "ghz",
    "g", "kg", "mg", "t",
    "mm", "cm", "m", "km",
    "mm2", "mm3", "cm2", "cm3", "m2", "m3",
    "mm²", "mm³", "cm²", "cm³", "m²", "m³",
    "pa", "kpa", "mpa", "bar",
    "ah", "mah", "awg", "db",
    "s", "ms", "us", "ns",
    "pct",
}
_NATURAL_LANGUAGE_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "that", "this", "these", "those",
    "system", "module", "product", "description", "website", "official", "support",
    "maximum", "minimum", "combiner", "box", "photovoltaic", "intelligent",
}


def _strip_markers(text: str) -> str:
    return re.sub(r"\*{1,3}|~~", "", text).strip()


def _cjk_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _latin_count(text: str) -> int:
    return sum(1 for ch in text if ch.isascii() and ch.isalpha())


def _normalized_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", "", _strip_markers(left))
    right_norm = re.sub(r"\s+", "", _strip_markers(right))
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _is_neutral_passthrough_token(text: str) -> bool:
    text = _strip_markers(text)
    if not text:
        return False
    if _CIRCLED_NUM_RE.match(text) or _STEP_NUM_RE.match(text) or _ROMAN_RE.match(text):
        return True
    if _CODE_TOKEN_RE.match(text):
        return True
    return False


def _looks_like_nonlinguistic_identifier(text: str) -> bool:
    text = _strip_markers(text)
    if not text:
        return False
    if _is_neutral_passthrough_token(text):
        return True
    if _cjk_count(text) > 0:
        return False
    if not any(ch.isdigit() for ch in text):
        return False

    alpha_tokens = re.findall(r"[A-Za-z]+(?:/[A-Za-z]+)?", text)
    if not alpha_tokens:
        return True
    if len(alpha_tokens) > 4:
        return False

    for token in alpha_tokens:
        normalized = token.lower().replace("^2", "2").replace("^3", "3")
        if normalized in _UNIVERSAL_UNIT_TOKENS:
            continue
        if token.isupper() and len(token) <= 8:
            continue
        if normalized not in _NATURAL_LANGUAGE_STOPWORDS and len(token) > 3 and not token.isupper():
            return False
    return True


def is_universal_notranslate_expression(text: str) -> bool:
    text = _strip_markers(text)
    if not text:
        return False
    if _is_neutral_passthrough_token(text):
        return True
    if _cjk_count(text) > 0:
        return False
    if not any(ch.isdigit() for ch in text):
        return False
    if not _UNIVERSAL_ALLOWED_RE.match(text):
        return False

    alpha_tokens = re.findall(r"[A-Za-zµμΩ²³]+", text)
    for token in alpha_tokens:
        normalized = (
            token.lower()
            .replace("μ", "µ")
            .replace("^2", "2")
            .replace("^3", "3")
        )
        if normalized not in _UNIVERSAL_UNIT_TOKENS:
            return False
    return True


def is_translation_required(
    source: str,
    source_lang: str = "",
    target_lang: str = "",
) -> bool:
    """True when the segment carries natural-language meaning and should be translated."""
    text = _strip_markers(source)
    if not text:
        return False
    if is_universal_notranslate_expression(text):
        return False
    if _looks_like_nonlinguistic_identifier(text):
        return False

    cjk_count = _cjk_count(text)
    latin_count = _latin_count(text)
    language_chars = cjk_count + latin_count

    if language_chars == 0:
        return False
    if cjk_count > 0:
        return True
    if source_lang.startswith("zh") and target_lang.startswith("en"):
        return False
    return True


def _is_high_similarity_same_language_copy(
    source: str,
    translation: str,
    *,
    source_lang: str,
    target_lang: str,
) -> bool:
    similarity = _normalized_similarity(source, translation)
    if similarity < 0.82:
        return False

    src_cjk = _cjk_count(source)
    src_latin = _latin_count(source)
    tgt_cjk = _cjk_count(translation)
    tgt_latin = _latin_count(translation)

    if source_lang.startswith("zh") and target_lang.startswith("en"):
        if src_cjk < 4 or tgt_cjk < 3:
            return False
        if tgt_cjk <= tgt_latin:
            return False
        return True

    if source_lang.startswith("en") and target_lang.startswith("zh"):
        if src_latin < 6 or tgt_latin < 4:
            return False
        if tgt_latin <= tgt_cjk:
            return False
        return True

    return False


def is_source_already_target_language(source: str, target_lang: str = "") -> bool:
    """True when a source segment is already predominantly in the target language."""
    if not target_lang:
        return False

    text = _strip_markers(source)
    if not text:
        return False
    if not is_translation_required(source, target_lang=target_lang):
        return True

    cjk_count = _cjk_count(text)
    latin_count = _latin_count(text)
    language_chars = cjk_count + latin_count
    if language_chars == 0:
        return False

    # Mixed source/target-language segments should still go through translation
    # so the source-language fragments can be converted while target-language
    # fragments are preserved.
    if cjk_count > 0 and latin_count > 0:
        return False

    if target_lang.startswith("en"):
        return latin_count >= 3 and latin_count / language_chars >= 0.75

    if target_lang.startswith("zh"):
        return cjk_count >= 2 and cjk_count / language_chars >= 0.75

    return False


def is_likely_misaligned(source: str, translation: str) -> bool:
    """Heuristic: short label translated as paragraph, or paragraph as label."""
    src = _strip_markers(source)
    tgt = _strip_markers(translation)
    if not src or not tgt:
        return False

    src_len = len(src)
    tgt_len = len(tgt)
    src_cjk = _cjk_count(src)

    src_is_label = bool(
        _CIRCLED_NUM_RE.match(src)
        or _STEP_NUM_RE.match(src)
        or _ROMAN_RE.match(src)
        or _is_neutral_passthrough_token(src)
    )
    tgt_is_label = bool(
        _CIRCLED_NUM_RE.match(tgt)
        or _STEP_NUM_RE.match(tgt)
        or _ROMAN_RE.match(tgt)
        or _is_neutral_passthrough_token(tgt)
        or _looks_like_nonlinguistic_identifier(tgt)
        or (tgt_len <= 4 and not tgt.isascii())
    )

    if src_is_label and tgt_len > 30:
        return True
    if (
        is_translation_required(src)
        and tgt_is_label
        and (
            src_len > 30
            or (src_cjk >= 4 and tgt_len <= max(12, int(src_len * 0.60)))
        )
    ):
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
        if not is_translation_required(source, source_lang=source_lang, target_lang=target_lang):
            return False
        return True

    if not source_lang or not target_lang:
        return False

    if _is_high_similarity_same_language_copy(
        source,
        translation,
        source_lang=source_lang,
        target_lang=target_lang,
    ):
        return True

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
    if not is_translation_required(source, source_lang=source_lang, target_lang=target_lang):
        return False
    if expected_id and returned_id and expected_id != returned_id:
        return True
    if not translation.strip():
        return True
    if is_untranslated_copy(source, translation, source_lang, target_lang):
        return True
    return is_likely_misaligned(source, translation)
