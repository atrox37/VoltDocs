from __future__ import annotations

from io import BytesIO

import openpyxl


def export_excel(original_bytes: bytes, parsed_segments: list[dict], request_segments: list[dict]) -> bytes:
    workbook = openpyxl.load_workbook(BytesIO(original_bytes))
    renamed_sheets: dict[str, str] = {}
    for parsed, request in zip(parsed_segments, request_segments):
        translation = (request.get("translation") or request.get("draftTranslation") or request.get("draft_translation") or "").strip()
        if not translation:
            continue
        original_sheet_name = renamed_sheets.get(parsed["sheet"], parsed["sheet"])
        sheet = workbook[original_sheet_name]
        if parsed.get("segment_type") == "sheet_title":
            sheet.title = translation
            renamed_sheets[parsed["sheet"]] = translation
            continue
        sheet[parsed["cell"]] = translation

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
