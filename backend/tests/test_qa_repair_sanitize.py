from services.qa_repair_ai import _parse_segments, sanitize_repair_text


def test_sanitize_repair_text_strips_prompt_xml() -> None:
    raw = (
        "<source>**5.1打样装配图片** 58</source>"
        "<current_translation>**5.1 Sample Assembly Drawings** 58</current_translation>"
        "<corrected_translation>**5.1 Sample Assembly Drawings**</corrected_translation>"
    )
    assert sanitize_repair_text(raw) == "**5.1 Sample Assembly Drawings**"


def test_sanitize_repair_text_fixes_escaped_markers() -> None:
    assert sanitize_repair_text(r"\*\*5.1 Sample Assembly Drawings\*\*\\") == "**5.1 Sample Assembly Drawings**"


def test_parse_segments_json_lines() -> None:
    raw = '{"id": "seg-1", "translation": "Hello"}\n{"id": "seg-2", "translation": "World"}'
    parsed = _parse_segments(raw, {"seg-1", "seg-2"})
    assert parsed == {"seg-1": "Hello", "seg-2": "World"}


def test_parse_segments_rejects_xml_echo() -> None:
    raw = (
        '<seg id="seg-1">'
        "<source>原文</source><current_translation>bad</current_translation>"
        "</seg>"
    )
    parsed = _parse_segments(raw, {"seg-1"})
    assert parsed == {}
