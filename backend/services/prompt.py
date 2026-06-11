from __future__ import annotations


def build_system_prompt(glossary: list[dict], source_lang: str, target_lang: str) -> str:
    if source_lang.startswith("zh") and target_lang.startswith("en"):
        direction = "Chinese text into English"
    elif source_lang.startswith("en") and target_lang.startswith("zh"):
        direction = "English text into Chinese"
    else:
        direction = f"{source_lang} into {target_lang}"

    glossary_lines = [f"- {item['source']} -> {item['target']}" for item in glossary]
    glossary_section = ""
    if glossary_lines:
        glossary_section = "\nTerminology pairs to follow exactly when they appear in the source:\n" + "\n".join(glossary_lines)
    return (
        f"You are a professional technical translator. Translate the provided {direction} from Word or spreadsheet documents.\n"
        "Keep the meaning accurate, direct, and suitable for engineering or operational documentation.\n"
        "If formatting markers such as **bold**, *italic*, or ~~strikethrough~~ appear in the source text, preserve them exactly.\n"
        "Output only translated text.\n"
        "Do not add notes, explanations, headers, or quotation marks.\n"
        "For spreadsheet cells, translate only the visible text content and do not add explanations.\n"
        "Preserve numbers, units, model codes, and warning labels exactly.\n"
        f"{glossary_section}"
    )
