from __future__ import annotations

from database import Database


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
    combined = "\n".join(segment_texts)
    matched: list[dict] = []
    used_chars = 0
    for item in sorted(terms, key=lambda row: -len(row.get("source", ""))):
        source_term = item.get("source", "")
        if source_term and source_term.lower() in combined.lower():
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
