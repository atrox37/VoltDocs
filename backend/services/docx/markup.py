"""DOCX inline marker helpers shared by parser and exporter."""
from __future__ import annotations

import re

_CIRCLED_NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_RE = re.compile(rf"^[{_CIRCLED_NUMS}]")
_ADJACENT_BOLD_RE = re.compile(r"(\*\*[^*]+?\*\*)(\*\*)")
_SEG_OPEN_RE = re.compile(r"^<seg\s+id=\"[^\"]+\"\s*>", re.IGNORECASE)
_SEG_ANY_RE = re.compile(r"</?seg\b[^>]*>", re.IGNORECASE)
_PLACEHOLDER_ONLY_RE = re.compile(
    r"^(?:"
    r"translated text"
    r"|\[translated content\]"
    r"|original_id"
    r"|<\s*translated\s+text\s*>"
    r"|<\s*translation\s*>"
    r"|<\s*original_id\s*>"
    r")$",
    re.IGNORECASE,
)


def strip_inline_markers(text: str) -> str:
    """Remove ** / * / ~~ markers for plain-text export (e.g. TOC fields)."""
    return re.sub(r"\*{1,3}|~~", "", text)


def clean_translation_artifacts(text: str, *, target_lang: str = "") -> str:
    """Remove model/XML leakage and normalize spacing from a translation string."""
    if not text:
        return ""

    result = text.strip()
    if _PLACEHOLDER_ONLY_RE.match(result):
        return ""
    while _SEG_OPEN_RE.match(result):
        result = _SEG_OPEN_RE.sub("", result, count=1).strip()
    result = _SEG_ANY_RE.sub("", result)
    if _PLACEHOLDER_ONLY_RE.match(result):
        return ""
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r",(?=[^\s\d])", ", ", result)
    result = re.sub(r",\s+(?=[^\d])", ", ", result)

    if target_lang.startswith("en"):
        result = result.replace("。", ".")
        result = re.sub(r"\.\s*\.", ".", result)

    return result.strip()


def normalize_adjacent_bold_markers(marked: str) -> str:
    """Turn **A****B** (adjacent bold runs) into **A** **B** for cleaner model input."""
    if "****" not in marked:
        return marked
    return re.sub(r"\*\*\*\*(?=[^*])", "** **", marked)


def normalize_marker_spacing(text: str) -> str:
    """Insert spaces between adjacent ** markers so export preserves word boundaries."""
    if not text or "**" not in text:
        return text

    prev = None
    result = text
    while prev != result:
        prev = result
        result = _ADJACENT_BOLD_RE.sub(r"\1 \2", result)
        result = re.sub(
            r"(\*\*[^*]+?\*\*)(?=[A-Za-z\u4e00-\u9fff])",
            r"\1 ",
            result,
        )
        result = re.sub(
            r"(\d)(\*\*[A-Za-z\u4e00-\u9fff])",
            r"\1 \2",
            result,
        )
    return re.sub(r"  +", " ", result)


def preserve_circled_prefix(source: str, translation: str) -> str:
    """Keep circled-number prefix from source when the model drops it."""
    src = source.strip()
    tgt = translation.strip()
    if not src or not tgt:
        return translation

    m = _CIRCLED_RE.match(src)
    if not m:
        return translation

    prefix = m.group(0)
    if prefix in tgt:
        return translation
    return f"{prefix}{tgt}" if tgt else prefix
