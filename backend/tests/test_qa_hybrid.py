import pytest

from services.qa_ai import AiQaVerdict
from services.qa_hybrid import _finalize_ai_verdict, evaluate_segments_qa, evaluate_segments_qa_with_repair


def test_finalize_ai_verdict_pass_high_confidence() -> None:
    verdict = AiQaVerdict("seg-1", True, 0.9, None)
    passed, reason = _finalize_ai_verdict(verdict, "numbers mismatch", 0.75)
    assert passed is True
    assert reason is None


def test_finalize_ai_verdict_pass_low_confidence() -> None:
    verdict = AiQaVerdict("seg-1", True, 0.5, "probably equivalent")
    passed, reason = _finalize_ai_verdict(verdict, "numbers mismatch", 0.75)
    assert passed is False
    assert reason is not None
    assert "Manual confirmation required" in reason


def test_finalize_ai_verdict_fail() -> None:
    verdict = AiQaVerdict("seg-1", False, 0.95, "amount is wrong")
    passed, reason = _finalize_ai_verdict(verdict, "numbers mismatch", 0.75)
    assert passed is False
    assert reason == "AI QA: amount is wrong"


@pytest.mark.asyncio
async def test_evaluate_segments_qa_hard_failure_skips_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_adjudicate(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("services.qa_hybrid.adjudicate_soft_failures", fake_adjudicate)

    segments = [{"id": "seg-1", "source_text": "**Important**"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "Important"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=True,
        bedrock_model_id="test-model",
    )
    assert called is False
    assert results["seg-1"]["qa_pass"] is False
    assert results["seg-1"]["qa_rule_name"] == "check_inline_markers"
    assert results["seg-1"]["qa_failure_type"] == "formatting"


@pytest.mark.asyncio
async def test_evaluate_segments_qa_ai_overrides_soft_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_adjudicate(items, **_kwargs):
        return {
            item["id"]: AiQaVerdict(item["id"], True, 0.95, None)
            for item in items
        }

    monkeypatch.setattr("services.qa_hybrid.adjudicate_soft_failures", fake_adjudicate)

    segments = [{"id": "seg-1", "source_text": "Delivery is scheduled for 11 month."}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "Delivery is scheduled for November."},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=True,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is True
    assert results["seg-1"]["qa_reason"] is None
    assert results["seg-1"]["qa_rule_name"] is None


@pytest.mark.asyncio
async def test_evaluate_segments_qa_soft_failure_without_ai() -> None:
    segments = [{"id": "seg-1", "source_text": "Quantity is 12."}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "Quantity is twelve."},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is False
    assert results["seg-1"]["qa_rule_name"] == "check_numbers"
    assert results["seg-1"]["qa_failure_type"] == "numbers"


@pytest.mark.asyncio
async def test_evaluate_segments_qa_does_not_flag_context_only_mismatch_without_ai() -> None:
    segments = [
        {"id": "seg-1", "source_text": "2025 Q3 OKR - Zhiyuan Wang"},
        {
            "id": "seg-2",
            "source_text": "Lead the front-end development of the platform and ensure stable operation after launch.",
        },
        {"id": "seg-3", "source_text": "Overall Objective"},
    ]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={
            "seg-1": "2025 Q3 OKR - Zhiyuan Wang",
            "seg-2": "2025 Q3 OKR - Zhiyuan Wang",
            "seg-3": "Overall Objective",
        },
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        bedrock_model_id="test-model",
    )
    assert results["seg-2"]["qa_pass"] is True
    assert results["seg-2"]["qa_reason"] is None


@pytest.mark.asyncio
async def test_evaluate_segments_qa_flags_untranslated_copy_as_hard_failure() -> None:
    segments = [{"id": "seg-1", "source_text": "实现移动端框架和ruleflow功能搭建"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "实现移动端框架和ruleflow功能搭建"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=True,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is False
    assert results["seg-1"]["qa_rule_name"] == "check_untranslated_copy"


@pytest.mark.asyncio
async def test_evaluate_segments_qa_flags_label_expansion_as_hard_failure() -> None:
    segments = [{"id": "seg-1", "source_text": "KR1.1"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "KR1.1: Connect to various points of the device module in the edge EMS"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=True,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is False
    assert results["seg-1"]["qa_rule_name"] == "check_segment_alignment"


@pytest.mark.asyncio
async def test_evaluate_segments_qa_skips_passthrough_identifier_segments() -> None:
    segments = [{"id": "seg-1", "source_text": "EN 61439-2:2011 / IEC 61439-2 ed. 3.0"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "EN 61439-2:2011 / IEC 61439-2 ed. 3.0"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is True
    assert results["seg-1"]["qa_reason"] is None


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_fixes_markers_rule_based() -> None:
    segments = [{"id": "seg-1", "source_text": "Prepare at least **2** plans"}]
    results, drafts, qa_profile = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id={"seg-1": "Prepare at least 2 plans"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_repair_enabled=True,
        qa_repair_max_attempts=1,
        bedrock_model_id="",
    )
    assert "**2**" in drafts["seg-1"]
    assert results["seg-1"]["qa_pass"] is True
    assert qa_profile["summary"]["roundCount"] >= 2


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_ai_for_empty_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_repair(items, **_kwargs):
        return {item["id"]: f"Translated: {item['source']}" for item in items}

    monkeypatch.setattr("services.qa_hybrid.repair_segments_batch", fake_repair)

    segments = [{"id": "seg-1", "source_text": "Inverter rated power"}]
    results, drafts, qa_profile = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id={"seg-1": ""},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        qa_repair_enabled=True,
        qa_repair_max_attempts=1,
        bedrock_model_id="test-model",
    )
    assert drafts["seg-1"].startswith("Translated:")
    assert results["seg-1"]["qa_pass"] is True
    assert qa_profile["summary"]["stoppedSegments"] == 0


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_stops_after_same_rule_without_improvement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def fake_repair(items, **_kwargs):
        calls.append(len(items))
        return {}

    monkeypatch.setattr("services.qa_hybrid.repair_segments_batch", fake_repair)

    segments = [{"id": "seg-1", "source_text": "Inverter rated power"}]
    results, drafts, qa_profile = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id={"seg-1": ""},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        qa_repair_enabled=True,
        qa_repair_max_attempts=3,
        bedrock_model_id="test-model",
    )

    assert drafts["seg-1"] == ""
    assert results["seg-1"]["qa_pass"] is False
    assert results["seg-1"]["qa_rule_name"] == "check_empty"
    assert results["seg-1"]["qa_failure_type"] == "other"
    assert results["seg-1"]["qa_debug"]["stoppedEarly"] is True
    assert len(results["seg-1"]["qa_debug"]["history"]) == 2
    assert qa_profile["summary"]["mostCommonRuleName"] == "check_empty"
    assert qa_profile["summary"]["failureTypes"]["other"] >= 1
    assert qa_profile["summary"]["stoppedSegments"] == 1
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_evaluate_segments_qa_flags_near_identical_untranslated_copy_as_hard_failure() -> None:
    segments = [{"id": "seg-1", "source_text": "实现移动端框架和ruleflow功能搭建，跟进云端运维与边端实施功能的页面更新"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "实现移动端框架和ruleflow功能搭建, 跟进云端运维与边端实施功能的页面更新"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=True,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is False
    assert results["seg-1"]["qa_rule_name"] == "check_untranslated_copy"
