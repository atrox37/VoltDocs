import pytest

from services.qa_ai import AiQaVerdict
from services.qa_hybrid import _finalize_ai_verdict, evaluate_segments_qa


def test_finalize_ai_verdict_pass_high_confidence() -> None:
    verdict = AiQaVerdict("seg-1", True, 0.9, None)
    passed, reason = _finalize_ai_verdict(verdict, "数字不一致", 0.75)
    assert passed is True
    assert reason is None


def test_finalize_ai_verdict_pass_low_confidence() -> None:
    verdict = AiQaVerdict("seg-1", True, 0.5, "可能等价")
    passed, reason = _finalize_ai_verdict(verdict, "数字不一致", 0.75)
    assert passed is False
    assert reason is not None
    assert "待人工确认" in reason


def test_finalize_ai_verdict_fail() -> None:
    verdict = AiQaVerdict("seg-1", False, 0.95, "金额错误")
    passed, reason = _finalize_ai_verdict(verdict, "数字不一致", 0.75)
    assert passed is False
    assert reason == "AI 质检: 金额错误"


@pytest.mark.asyncio
async def test_evaluate_segments_qa_hard_failure_skips_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_adjudicate(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("services.qa_hybrid.adjudicate_soft_failures", fake_adjudicate)

    segments = [{"id": "seg-1", "source_text": "**重要**"}]
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
    assert "格式标记" in (results["seg-1"]["qa_reason"] or "")


@pytest.mark.asyncio
async def test_evaluate_segments_qa_ai_overrides_soft_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_adjudicate(items, **_kwargs):
        return {
            item["id"]: AiQaVerdict(item["id"], True, 0.95, None)
            for item in items
        }

    monkeypatch.setattr("services.qa_hybrid.adjudicate_soft_failures", fake_adjudicate)

    segments = [{"id": "seg-1", "source_text": "交期为11月。"}]
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


@pytest.mark.asyncio
async def test_evaluate_segments_qa_soft_failure_without_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_adjudicate(*_args, **_kwargs):
        raise AssertionError("AI should not be called when disabled")

    monkeypatch.setattr("services.qa_hybrid.adjudicate_soft_failures", fake_adjudicate)

    segments = [{"id": "seg-1", "source_text": "数量为12。"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "Quantity is twelve."},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        bedrock_model_id="test-model",
    )
    assert results["seg-1"]["qa_pass"] is False
    assert "数字不一致" in (results["seg-1"]["qa_reason"] or "")


@pytest.mark.asyncio
async def test_evaluate_segments_qa_thousand_separator_passes_without_ai() -> None:
    segments = [{"id": "seg-1", "source_text": "价格为1000元。"}]
    results = await evaluate_segments_qa(
        segments=segments,
        drafts_by_id={"seg-1": "The price is 1,000 yuan."},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
    )
    assert results["seg-1"]["qa_pass"] is True


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_fixes_markers_rule_based() -> None:
    from services.qa_hybrid import evaluate_segments_qa_with_repair

    segments = [{"id": "seg-1", "source_text": "准备不少于 **2** 套方案"}]
    results, drafts = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id={"seg-1": "prepare no less than 2 plans"},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_repair_enabled=True,
        qa_repair_max_attempts=1,
        bedrock_model_id="",
    )
    assert "**2**" in drafts["seg-1"]
    assert results["seg-1"]["qa_pass"] is True


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_ai_for_empty_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.qa_hybrid import evaluate_segments_qa_with_repair

    async def fake_repair(items, **_kwargs):
        return {item["id"]: f"Translated: {item['source']}" for item in items}

    monkeypatch.setattr("services.qa_hybrid.repair_segments_batch", fake_repair)

    segments = [{"id": "seg-1", "source_text": "逆变器额定功率"}]
    results, drafts = await evaluate_segments_qa_with_repair(
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


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_retries_when_batch_returns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.qa_hybrid import evaluate_segments_qa_with_repair

    calls: list[int] = []

    async def fake_repair(items, **_kwargs):
        calls.append(len(items))
        if len(items) > 1:
            return {}
        return {items[0]["id"]: f"Fixed: {items[0]['source']}"}

    monkeypatch.setattr("services.qa_hybrid.repair_segments_batch", fake_repair)

    segments = [
        {"id": "seg-1", "source_text": "逆变器额定功率"},
        {"id": "seg-2", "source_text": "汇流箱"},
    ]
    results, drafts = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id={"seg-1": "", "seg-2": ""},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        qa_repair_enabled=True,
        qa_repair_max_attempts=1,
        bedrock_model_id="test-model",
    )
    assert calls[0] == 2
    assert 1 in calls[1:]
    assert drafts["seg-1"].startswith("Fixed:")
    assert drafts["seg-2"].startswith("Fixed:")
    assert results["seg-1"]["qa_pass"] is True
    assert results["seg-2"]["qa_pass"] is True


@pytest.mark.asyncio
async def test_evaluate_segments_qa_with_repair_fixes_untranslated_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.qa_hybrid import evaluate_segments_qa_with_repair

    async def fake_repair(items, **_kwargs):
        return {
            item["id"]: "**1.1 Purpose and Importance of the Installation Manual** 5"
            for item in items
        }

    monkeypatch.setattr("services.qa_hybrid.repair_segments_batch", fake_repair)

    source = "**1.1 安装手册的目的及重要性** 5"
    segments = [{"id": "seg-1", "source_text": source}]
    results, drafts = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id={"seg-1": source},
        source_lang="zh-CN",
        target_lang="en-US",
        qa_ai_enabled=False,
        qa_repair_enabled=True,
        qa_repair_max_attempts=1,
        bedrock_model_id="test-model",
    )
    assert "Installation Manual" in drafts["seg-1"]
    assert results["seg-1"]["qa_pass"] is True
