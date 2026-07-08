from services.translation_align import (
    is_translation_required,
    is_likely_misaligned,
    is_source_already_target_language,
    is_universal_notranslate_expression,
    is_untranslated_copy,
    needs_retranslation,
)


def test_is_likely_misaligned_circled_number() -> None:
    assert is_likely_misaligned("①", "Fix the beam frame end using the pin shaft") is True
    assert is_likely_misaligned(
        "Fix the beam frame end using the 12X80 pin shaft (ES2D12-080-1-HDG).",
        "①",
    ) is True


def test_is_likely_misaligned_normal_translation() -> None:
    assert is_likely_misaligned(
        "Fix the beam frame end using the 12X80 pin shaft (ES2D12-080-1-HDG).",
        "Fix the beam frame end using the 12X80 pin shaft (ES2D12-080-1-HDG).",
    ) is False


def test_is_untranslated_copy_detects_identical_text() -> None:
    source = "**安装手册的目的及重要性** 5"
    assert is_untranslated_copy(source, source, "zh-CN", "en-US") is True


def test_is_untranslated_copy_detects_near_identical_source_language_copy() -> None:
    source = "实现移动端框架和ruleflow功能搭建，跟进云端运维与边端实施功能的页面更新"
    translation = "实现移动端框架和ruleflow功能搭建, 跟进云端运维与边端实施功能的页面更新"
    assert is_untranslated_copy(source, translation, "zh-CN", "en-US") is True


def test_source_already_target_language_allows_english_passthrough() -> None:
    source = "Ensure the continuous and stable operation of the EMS system."

    assert is_source_already_target_language(source, "en-US") is True
    assert needs_retranslation(source, source, source_lang="zh-CN", target_lang="en-US") is False


def test_source_already_target_language_requires_dominant_target_language() -> None:
    source = "保持系统稳定 operation"

    assert is_source_already_target_language(source, "en-US") is False


def test_is_untranslated_copy_allows_translated_text() -> None:
    source = "**安装手册的目的及重要性** 5"
    translation = "**Purpose and Importance of the Installation Manual** 5"
    assert is_untranslated_copy(source, translation, "zh-CN", "en-US") is False


def test_code_like_tokens_are_allowed_as_passthrough() -> None:
    assert is_source_already_target_language("KR2.4", "en-US") is True
    assert is_source_already_target_language("O3", "en-US") is True
    assert is_untranslated_copy("KR2.4", "KR2.4", "zh-CN", "en-US") is False


def test_identifier_like_standard_numbers_do_not_require_translation() -> None:
    assert is_translation_required("EN 61439-2", "zh-CN", "en-US") is False
    assert is_source_already_target_language("EN 61439-2", "en-US") is True
    assert is_untranslated_copy("EN 61439-2", "EN 61439-2", "zh-CN", "en-US") is False


def test_chinese_labels_and_sentences_still_require_translation() -> None:
    assert is_translation_required("基本信息", "zh-CN", "en-US") is True
    assert is_translation_required("用于避免绝缘故障导致整段发电场停机", "zh-CN", "en-US") is True


def test_universal_numeric_unit_expressions_are_allowed_as_passthrough() -> None:
    assert is_universal_notranslate_expression("20 A") is True
    assert is_universal_notranslate_expression("≥ 1000 V") is True
    assert is_universal_notranslate_expression("600 × 500 × 172 mm") is True
    assert is_source_already_target_language("4 mm²", "en-US") is True
    assert is_untranslated_copy("23 kg", "23 kg", "zh-CN", "en-US") is False


def test_code_like_tokens_detect_misaligned_paragraph_replacement() -> None:
    assert is_likely_misaligned(
        "O3",
        "Ensure that the current cloud platform and edge project functions are kept up-to-date and run stably.",
    ) is True


def test_code_replacement_of_natural_language_is_misaligned() -> None:
    assert is_likely_misaligned("1.5 mm² 低阻抗四芯双绞线", "PG16-14G") is True


def test_short_spec_translations_are_not_misaligned() -> None:
    assert is_likely_misaligned("IP65或IP66", "IP65 or IP66") is False
    assert is_likely_misaligned("最大 1500 V DC", "Maximum 1500 V DC") is False
    assert is_likely_misaligned("-25 °C 至 40 °C", "-25 °C to 40 °C") is False
