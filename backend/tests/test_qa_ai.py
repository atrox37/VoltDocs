import pytest

from services.qa_ai import AiQaVerdict, _parse_verdicts


def test_parse_verdicts_from_json_array() -> None:
    raw = """[
      {"id": "seg-1", "pass": true, "confidence": 0.95, "reason": null},
      {"id": "seg-2", "pass": false, "confidence": 0.9, "reason": "数字不一致"}
    ]"""
    verdicts = _parse_verdicts(raw, {"seg-1", "seg-2"})
    assert verdicts["seg-1"] == AiQaVerdict("seg-1", True, 0.95, None)
    assert verdicts["seg-2"].pass_ is False
    assert verdicts["seg-2"].reason == "数字不一致"


def test_parse_verdicts_from_markdown_fence() -> None:
    raw = """```json
[{"id": "seg-1", "pass": true, "confidence": 0.8, "reason": null}]
```"""
    verdicts = _parse_verdicts(raw, {"seg-1"})
    assert verdicts["seg-1"].pass_ is True


def test_parse_verdicts_clamps_confidence() -> None:
    raw = '[{"id": "seg-1", "pass": true, "confidence": 1.5, "reason": null}]'
    verdicts = _parse_verdicts(raw, {"seg-1"})
    assert verdicts["seg-1"].confidence == 1.0


def test_parse_verdicts_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        _parse_verdicts("not json at all", {"seg-1"})
