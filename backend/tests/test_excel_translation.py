from __future__ import annotations

from io import BytesIO

import openpyxl

from services.excel_exporter import export_excel
from services.excel_parser import extract_segments


def _make_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "安装说明"
    sheet["A1"] = "模块"
    sheet["A2"] = "12345"

    hidden = workbook.create_sheet("隐藏页")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "不应处理"

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_extract_segments_includes_visible_sheet_titles() -> None:
    content = _make_workbook()

    segments = extract_segments(content)

    assert [segment["segment_type"] for segment in segments] == ["sheet_title", "cell"]
    assert segments[0]["source_text"] == "安装说明"
    assert segments[0]["sheet"] == "安装说明"
    assert segments[1]["cell"] == "A1"


def test_export_excel_translates_sheet_titles_and_cells() -> None:
    original = _make_workbook()
    segments = extract_segments(original)

    translated = export_excel(
        original,
        segments,
        [
            {"translation": "Installation Guide"},
            {"translation": "Module"},
        ],
    )

    workbook = openpyxl.load_workbook(BytesIO(translated))
    assert workbook.sheetnames == ["Installation Guide", "隐藏页"]
    assert workbook["Installation Guide"]["A1"].value == "Module"
    assert workbook["隐藏页"]["A1"].value == "不应处理"
