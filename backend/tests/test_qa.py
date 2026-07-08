from services.qa import (
    check_empty,
    check_inline_markers,
    check_numbers,
    is_soft_failure_rule,
    run_all_checks,
    run_hard_checks,
    run_soft_checks,
)


def test_check_numbers_allows_chinese_month_with_inline_markers() -> None:
    source = "完成 RE+（**11月**）展会大屏项目开发与部署保障；准备不少于 **2** 套演示兜底方案。"
    translation = (
        "Complete the development and deployment guarantee of the large screen project "
        "for the RE+ (**November**) exhibition: prepare no less than **2** backup demonstration plans."
    )
    assert check_numbers(source, translation) is None


def test_check_numbers_allows_month_abbreviation_with_period() -> None:
    assert check_numbers("交期为11月。", "Delivery is scheduled for Nov.") is None


def test_check_numbers_allows_chinese_month_to_english_month_name() -> None:
    assert check_numbers("交期为11月。", "Delivery is scheduled for November.") is None


def test_check_numbers_allows_chinese_month_to_english_month_abbreviation() -> None:
    assert check_numbers("计划在11月发布。", "Release is planned for Nov.") is None


def test_check_numbers_still_requires_non_month_numbers() -> None:
    reason = check_numbers("型号AB-123，交期为11月。", "Model AB-123, delivery is scheduled for November.")
    assert reason is None

    reason = check_numbers("数量为12。", "Quantity is twelve.")
    assert reason == "数字不一致，译文缺少: 12"


def test_check_numbers_allows_thousand_separator_variants() -> None:
    assert check_numbers("价格为1000元。", "The price is 1,000 yuan.") is None
    assert check_numbers("价格为1,000元。", "The price is 1000 yuan.") is None


def test_check_numbers_handles_decimal_without_month_conversion() -> None:
    assert check_numbers("Voltage is 6.09 V.", "Voltage is 6.09 V.") is None
    reason = check_numbers("Voltage is 6.09 V.", "Voltage is normal.")
    assert reason is not None
    assert "6.09" in reason


def test_hard_and_soft_rule_classification() -> None:
    hard_reason, hard_rule = run_hard_checks("原文", "")
    assert hard_reason == "译文为空"
    assert hard_rule == "check_empty"
    assert not is_soft_failure_rule(hard_rule)

    soft_reason, soft_rule = run_soft_checks("数量为12。", "Quantity is twelve.")
    assert soft_reason is not None
    assert soft_rule == "check_numbers"
    assert is_soft_failure_rule(soft_rule)


def test_hard_rules_block_before_soft_rules() -> None:
    reason, rule_name = run_hard_checks("**重要**", "Important")
    assert reason is not None
    assert rule_name == "check_inline_markers"

    reason = run_all_checks("**重要**", "Important")
    assert reason is not None


def test_inline_markers_is_hard_failure() -> None:
    reason, rule_name = run_hard_checks("**bold** text", "bold text")
    assert reason is not None
    assert rule_name == "check_inline_markers"
    assert not is_soft_failure_rule(rule_name)


def test_check_numbers_rejects_malformed_thousands_separator_spacing() -> None:
    reason = check_numbers("15,897.707 g", "15, 897.707 g")
    assert reason == "数字格式错误：千分位分隔符后存在非法空格"

    reason = check_numbers("最高1500V", "Maximum 1, 500 V")
    assert reason == "数字格式错误：千分位分隔符后存在非法空格"


def test_check_numbers_allows_unit_spacing_variants() -> None:
    assert check_numbers("1500V", "1,500 V") is None
