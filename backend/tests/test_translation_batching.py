from types import SimpleNamespace

import pytest

from routes.translation import _batch_limits_for_file_type
from services.translation import _finalize_draft, _split_into_batches, _translate_chunk_via_bedrock


def _batch_ids(batches: list[list[dict]]) -> list[list[str]]:
    return [[segment["id"] for segment in batch] for batch in batches]


def test_split_into_batches_allows_docx_segments_to_share_batches() -> None:
    segments = [
        {"id": "seg-1", "source_text": "Installation", "plain_text": "Installation", "segment_type": "title", "style_name": "Heading1"},
        {"id": "seg-2", "source_text": "Install the base frame and tighten all bolts.", "plain_text": "Install the base frame and tighten all bolts.", "segment_type": "paragraph", "style_name": "Normal"},
        {"id": "seg-3", "source_text": "Torque", "plain_text": "Torque", "segment_type": "cell", "style_name": "Sheet A"},
        {"id": "seg-4", "source_text": "45 Nm", "plain_text": "45 Nm", "segment_type": "cell", "style_name": "Sheet A"},
        {"id": "seg-5", "source_text": "Verify the final alignment after installation.", "plain_text": "Verify the final alignment after installation.", "segment_type": "paragraph", "style_name": "Normal"},
    ]

    batches = _split_into_batches(segments, max_bytes=5000, max_segments=120, file_type="docx")

    assert _batch_ids(batches) == [["seg-1", "seg-2", "seg-3", "seg-4", "seg-5"]]


def test_batch_limits_for_docx_allow_larger_batches_than_default_path() -> None:
    cfg = SimpleNamespace(translation_batch_max_bytes=5000, translation_batch_max_segments=40)

    assert _batch_limits_for_file_type("docx", cfg) == (3000, 50)


def test_batch_limits_for_md_use_the_same_compromise_as_docx() -> None:
    cfg = SimpleNamespace(translation_batch_max_bytes=5000, translation_batch_max_segments=40)

    assert _batch_limits_for_file_type("md", cfg) == (3000, 50)


def test_batch_limits_for_xlsx_use_the_same_compromise_as_docx() -> None:
    cfg = SimpleNamespace(translation_batch_max_bytes=5000, translation_batch_max_segments=40)

    assert _batch_limits_for_file_type("xlsx", cfg) == (3000, 50)


def test_split_into_batches_allows_xlsx_mixed_text_types_to_share_batches() -> None:
    segments = [
        {"id": "seg-1", "source_text": "O1", "plain_text": "O1", "segment_type": "cell", "style_name": "Sheet A"},
        {
            "id": "seg-2",
            "source_text": "Complete the front-end delivery and online acceptance verification materials for the platform.",
            "plain_text": "Complete the front-end delivery and online acceptance verification materials for the platform.",
            "segment_type": "cell",
            "style_name": "Sheet A",
        },
        {"id": "seg-3", "source_text": "KR1.1", "plain_text": "KR1.1", "segment_type": "cell", "style_name": "Sheet A"},
        {"id": "seg-4", "source_text": "Level", "plain_text": "Level", "segment_type": "cell", "style_name": "Sheet A"},
    ]

    batches = _split_into_batches(segments, max_bytes=5000, max_segments=120, file_type="xlsx")

    assert _batch_ids(batches) == [["seg-1", "seg-2", "seg-3", "seg-4"]]


def test_split_into_batches_preserves_oversized_xlsx_isolation() -> None:
    long_text = "Long paragraph " * 80
    segments = [
        {"id": "seg-1", "source_text": "Label", "plain_text": "Label", "segment_type": "cell", "style_name": "Sheet A"},
        {"id": "seg-2", "source_text": long_text, "plain_text": long_text, "segment_type": "cell", "style_name": "Sheet A"},
        {"id": "seg-3", "source_text": "Next label", "plain_text": "Next label", "segment_type": "cell", "style_name": "Sheet A"},
    ]

    batches = _split_into_batches(segments, max_bytes=5000, max_segments=120, file_type="xlsx")

    assert _batch_ids(batches) == [["seg-1"], ["seg-2"], ["seg-3"]]


def test_split_into_batches_respects_xlsx_50_segment_cap() -> None:
    segments = [
        {"id": f"seg-{index + 1}", "source_text": f"Cell {index + 1}", "plain_text": f"Cell {index + 1}", "segment_type": "cell", "style_name": "Sheet A"}
        for index in range(51)
    ]

    batches = _split_into_batches(segments, max_bytes=5000, max_segments=120, file_type="xlsx")

    assert _batch_ids(batches) == [
        [f"seg-{index + 1}" for index in range(50)],
        ["seg-51"],
    ]


@pytest.mark.asyncio
async def test_translate_chunk_via_bedrock_omits_batch_glossary_for_xlsx() -> None:
    captured: dict[str, object] = {}

    async def fake_translate_batch_bedrock(*, segments, source_lang, target_lang, glossary, model_id, region, aws_profile, all_glossary_terms):
        captured["segments"] = segments
        captured["glossary"] = glossary
        captured["all_glossary_terms"] = all_glossary_terms
        return [{"id": "seg-1", "translation": "translated"}]

    import services.translation as translation_module

    original = translation_module.translate_batch_bedrock
    translation_module.translate_batch_bedrock = fake_translate_batch_bedrock
    try:
        await _translate_chunk_via_bedrock(
            chunk=[{"id": "seg-1", "source_text": "Install bracket"}],
            source_lang="en-US",
            target_lang="zh-CN",
            glossary_terms=[{"source": "Install", "target": "АВзА"}],
            glossary_max_terms=10,
            glossary_max_prompt_chars=1000,
            model_id="us.amazon.nova-lite-v1:0",
            region="us-east-1",
            aws_profile=None,
        )
    finally:
        translation_module.translate_batch_bedrock = original

    payload = captured["segments"]
    assert payload[0]["glossary"] == [{"source": "Install", "target": "АВзА"}]
    assert captured["glossary"] == []
    assert captured["all_glossary_terms"] == [{"source": "Install", "target": "АВзА"}]


def test_finalize_draft_fixes_illegal_grouped_number_spaces() -> None:
    assert _finalize_draft("?? 1,500 V DC", "Maximum 1, 500 V DC", "en-US") == "Maximum 1,500 V DC"
    assert _finalize_draft("????? 150,000 ?", "delivered to over 150, 000 units", "en-US") == "delivered to over 150,000 units"


def test_finalize_draft_normalizes_english_heading_punctuation() -> None:
    assert _finalize_draft("5、分层功能概要", "5、Layered Function Overview", "en-US") == "5. Layered Function Overview"

