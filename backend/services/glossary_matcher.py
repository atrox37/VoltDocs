"""Glossary matching and post-translation terminology enforcement."""
from __future__ import annotations

import re

from database import Database


def _strip_inline_markers(text: str) -> str:
    return re.sub(r"\*{1,3}|~~", "", text)


def load_glossary_terms(
    db: Database,
    source_lang: str,
    target_lang: str,
) -> list[dict]:
    if source_lang == "en-US" and target_lang == "zh-CN":
        rows = db.query_all(
            """
            SELECT source_term, target_term
            FROM glossary_terms
            WHERE enabled = 1 AND source_lang = 'zh-CN' AND target_lang = 'en-US'
            """
        )
        return [
            {
                "source": row["target_term"],
                "target": row["source_term"],
            }
            for row in rows
        ]

    rows = db.query_all(
        """
        SELECT source_term, target_term
        FROM glossary_terms
        WHERE enabled = 1 AND source_lang = ? AND target_lang = ?
        """,
        (source_lang, target_lang),
    )
    return [
        {
            "source": row["source_term"],
            "target": row["target_term"],
        }
        for row in rows
    ]


def select_terms_for_texts(
    terms: list[dict],
    segment_texts: list[str],
    max_terms: int,
    max_prompt_chars: int,
) -> list[dict]:
    combined_plain = _strip_inline_markers("\n".join(segment_texts)).lower()

    matched: list[dict] = []
    used_chars = 0
    for item in sorted(terms, key=lambda row: -len(row.get("source", ""))):
        source_term = item.get("source", "")
        if source_term and source_term.lower() in combined_plain:
            next_size = used_chars + len(source_term) + len(item.get("target", ""))
            if next_size > max_prompt_chars:
                continue
            matched.append(
                {
                    "source": source_term,
                    "target": item.get("target", ""),
                }
            )
            used_chars = next_size
            if len(matched) >= max_terms:
                break
    return matched


def terms_for_source(
    terms: list[dict],
    source_text: str,
    source_lang: str,
    target_lang: str,
) -> list[dict]:
    """Return glossary entries that appear in a single segment."""
    del source_lang, target_lang
    if not terms:
        return []
    plain = _strip_inline_markers(source_text)
    plain_lower = plain.lower()
    matched: list[dict] = []
    for item in terms:
        src = item.get("source", "")
        tgt = item.get("target", "")
        if not src or not tgt:
            continue
        if src in plain or src.lower() in plain_lower:
            matched.append(
                {
                    "source": src,
                    "target": tgt,
                }
            )
    return matched


def apply_glossary_postprocess(
    source: str,
    translation: str,
    terms: list[dict],
    source_lang: str,
    target_lang: str,
) -> str:
    """Fix common model paraphrasing when glossary mandates an exact target phrase."""
    if not translation.strip() or not terms:
        return translation

    del source_lang, target_lang
    plain_src = _strip_inline_markers(source)
    result = translation
    plain_result = _strip_inline_markers(result).lower()

    for item in sorted(terms, key=lambda row: -len(row.get("source", ""))):
        src = item.get("source", "")
        tgt = item.get("target", "")
        if not src or not tgt:
            continue
        if src not in plain_src and src.lower() not in plain_src.lower():
            continue
        if tgt.lower() in plain_result:
            continue

        # Replace wrong phrase that shares a multi-word tail with the mandatory target.
        parts = tgt.split()
        if len(parts) >= 2:
            tail = " ".join(parts[1:])
            pattern = re.compile(rf"\b[\w][\w-]*(?:\s+[\w][\w-]*)*\s+{re.escape(tail)}\b", re.IGNORECASE)
            new_result, count = pattern.subn(tgt, result, count=1)
            if count:
                result = new_result
                plain_result = _strip_inline_markers(result).lower()
                continue

        # Replace paraphrases that keep the target prefix but drift on the last noun.
        if len(parts) >= 2:
            prefix = " ".join(parts[:-1])
            pattern = re.compile(rf"\b{re.escape(prefix)}\s+[\w-]+\b", re.IGNORECASE)
            new_result, count = pattern.subn(tgt, result, count=1)
            if count:
                result = new_result
                plain_result = _strip_inline_markers(result).lower()

    return result


def match_glossary_terms(
    db: Database,
    source_lang: str,
    target_lang: str,
    segment_texts: list[str],
    max_terms: int,
    max_prompt_chars: int,
) -> list[dict]:
    terms = load_glossary_terms(db, source_lang, target_lang)
    return select_terms_for_texts(terms, segment_texts, max_terms, max_prompt_chars)
