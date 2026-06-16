from services.qa_repair import repair_inline_markers, repair_strategy_for_rule


def test_repair_inline_markers_wraps_literal_number() -> None:
    source = "准备不少于 **2** 套演示兜底方案"
    translation = "prepare no less than 2 backup demonstration plans"
    fixed = repair_inline_markers(source, translation)
    assert "**2**" in fixed
    assert "no less than **2** backup" in fixed


def test_repair_inline_markers_wraps_model_code() -> None:
    source = "型号 **AB-123** 已停产"
    translation = "Model AB-123 has been discontinued"
    fixed = repair_inline_markers(source, translation)
    assert "**AB-123**" in fixed


def test_repair_inline_markers_no_change_without_literal_match() -> None:
    source = "完成 **11月** 展会"
    translation = "Complete the November exhibition"
    assert repair_inline_markers(source, translation) == translation


def test_repair_strategy_for_rule() -> None:
    assert repair_strategy_for_rule("check_empty") == "retranslate"
    assert repair_strategy_for_rule("check_inline_markers") == "markers"
    assert repair_strategy_for_rule("check_required_terms") == "glossary"


def test_repair_glossary_from_reason_replaces_list_of_materials() -> None:
    from services.qa_repair import repair_glossary_from_reason

    source = "1.2 物料清单"
    translation = "1.2 List of Materials Required for Installation"
    reason = "术语未按术语表翻译: 物料清单 → Bill of Materials"
    fixed = repair_glossary_from_reason(source, translation, reason)
    assert "Bill of Materials" in fixed
    assert "List of Materials" not in fixed


def test_repair_glossary_from_reason_replaces_base_plate() -> None:
    from services.qa_repair import repair_glossary_from_reason

    source = "地脚螺栓"
    translation = "anchor base plate bolts"
    reason = "术语未按术语表翻译: 地脚 → Base Foot"
    fixed = repair_glossary_from_reason(source, translation, reason)
    assert "Base Foot" in fixed
    assert "base plate" not in fixed.lower()
