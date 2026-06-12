from __future__ import annotations


def build_system_prompt(glossary: list[dict], source_lang: str, target_lang: str) -> str:
    if source_lang.startswith("zh") and target_lang.startswith("en"):
        direction = "Chinese text into English"
    elif source_lang.startswith("en") and target_lang.startswith("zh"):
        direction = "English text into Chinese"
    else:
        direction = f"{source_lang} into {target_lang}"

    glossary_lines = [
        f"- {item['source']} → {item['target']}"
        + (f"  [context: {item['context']}]" if item.get("context") else "")
        for item in glossary
    ]
    glossary_section = ""
    if glossary_lines:
        glossary_section = (
            "\n\nMANDATORY TERMINOLOGY — you MUST use these exact translations whenever the source term appears. "
            "Do NOT paraphrase, substitute, or omit them:\n"
            + "\n".join(glossary_lines)
        )
    return (
        f"You are a professional technical translator. Translate the provided {direction} from Word or spreadsheet documents.\n"
        "Keep the meaning accurate, direct, and suitable for engineering or operational documentation.\n"
        "Formatting markers present in the source text must be preserved exactly in the translation:\n"
        "  - **text** = bold → keep **text** in translation\n"
        "  - *text* = italic → keep *text* in translation\n"
        "  - ~~text~~ = strikethrough → keep ~~text~~ in translation\n"
        "  - Single ~ is NOT a formatting marker; treat the whole segment as plain text and translate it normally.\n"
        "Output only translated text. Do not add notes, explanations, headers, or quotation marks.\n"
        "For spreadsheet cells, translate only the visible text content.\n"
        "Preserve numbers, units, model codes, and warning labels exactly."
        + glossary_section
    )
