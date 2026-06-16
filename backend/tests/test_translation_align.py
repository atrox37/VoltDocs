from services.glossary_matcher import apply_glossary_postprocess, terms_for_source
from services.translation_align import is_likely_misaligned
from services.translation import _split_into_batches
from services.bedrock import is_short_segment, parse_seg_xml


def test_is_likely_misaligned_circled_number() -> None:
    assert is_likely_misaligned("③", "Fix the beam frame end using the pin shaft") is True
    assert is_likely_misaligned(
        "固定梁框架端使用“12X80销轴”(ES2D12-080-1-HDG) 固定",
        "④",
    ) is True


def test_is_likely_misaligned_normal_translation() -> None:
    assert is_likely_misaligned(
        "固定梁框架端使用“12X80销轴”(ES2D12-080-1-HDG) 固定",
        "Fix the beam frame end using the 12X80 pin shaft (ES2D12-080-1-HDG).",
    ) is False


def test_is_untranslated_copy_detects_identical_text() -> None:
    from services.translation_align import is_untranslated_copy

    source = "**1.1 安装手册的目的及重要性** 5"
    assert is_untranslated_copy(source, source, "zh-CN", "en-US") is True


def test_is_untranslated_copy_allows_english_translation() -> None:
    from services.translation_align import is_untranslated_copy

    source = "**1.1 安装手册的目的及重要性** 5"
    translation = "**1.1 Purpose and Importance of the Installation Manual** 5"
    assert is_untranslated_copy(source, translation, "zh-CN", "en-US") is False


def test_apply_glossary_postprocess_does_not_prepend_on_untranslated() -> None:
    source = "**运行状况**: 在整个滑动过程中，不得出现卡滞感"
    translation = source
    terms = [{"source": "卡滞", "target": "Jamming"}]
    fixed = apply_glossary_postprocess(source, translation, terms, "zh-CN", "en-US")
    assert fixed == source


def test_apply_glossary_postprocess_fixes_wrong_phrase() -> None:
    source = "各轴杆组合连接组件梁框架"
    translation = "Connect the Module Beam Frame assembly"
    terms = [{"source": "组件梁框架", "target": "Module Beam Frame"}]
    fixed = apply_glossary_postprocess(source, translation, terms, "zh-CN", "en-US")
    assert "Module Beam Frame" in fixed


def test_terms_for_source() -> None:
    terms = [{"source": "组件梁框架", "target": "Module Beam Frame"}]
    matched = terms_for_source(terms, "连接组件梁框架", "zh-CN", "en-US")
    assert len(matched) == 1


def test_batches_by_size_not_per_short_segment() -> None:
    segments = [
        {"id": "seg-1", "source_text": "③"},
        {"id": "seg-2", "source_text": "这是一段较长的正文内容，需要与序号分段翻译。"},
        {"id": "seg-3", "source_text": "④"},
    ]
    batches = _split_into_batches(segments, max_bytes=5000, max_segments=10)
    assert len(batches) == 1
    assert len(batches[0]) == 3


def test_is_short_segment() -> None:
    assert is_short_segment("③")
    assert not is_short_segment("这是一段较长的正文")


def test_parse_seg_xml_json_fallback() -> None:
    raw = '{"id": "seg-1", "translation": "Hello"}'
    assert parse_seg_xml(raw) == [{"id": "seg-1", "translation": "Hello"}]
