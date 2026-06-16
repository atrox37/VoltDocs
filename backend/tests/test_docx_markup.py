from services.docx.markup import normalize_marker_spacing, preserve_circled_prefix


def test_normalize_marker_spacing_adjacent_bold() -> None:
    raw = "**1.2****Bill of Materials****and Tools List**"
    fixed = normalize_marker_spacing(raw)
    assert "**1.2**" in fixed
    assert "Bill of Materials" in fixed
    assert " and " in fixed or "and Tools" in fixed


def test_preserve_circled_prefix() -> None:
    assert preserve_circled_prefix("⑤", "Insert the B-type open pin") == "⑤Insert the B-type open pin"
    assert preserve_circled_prefix("⑥固定件", "Fixed Piece") == "⑥Fixed Piece"
