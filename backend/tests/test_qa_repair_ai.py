import pytest

from services.qa_repair_ai import _parse_segments


def test_parse_segments_xml() -> None:
    raw = '<seg id="seg-1">**2** backup plans</seg>\n<seg id="seg-2">Fixed text</seg>'
    parsed = _parse_segments(raw, {"seg-1", "seg-2"})
    assert parsed["seg-1"] == "**2** backup plans"
    assert parsed["seg-2"] == "Fixed text"
