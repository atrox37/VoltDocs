from __future__ import annotations

from io import BytesIO

import openpyxl


def export_excel(original_bytes: bytes, parsed_segments: list[dict], request_segments: list[dict]) -> bytes:
    workbook = openpyxl.load_workbook(BytesIO(original_bytes))
    for parsed, request in zip(parsed_segments, request_segments):
        translation = (request.get("translation") or request.get("draftTranslation") or request.get("draft_translation") or "").strip()
        if not translation:
            continue
        sheet = workbook[parsed["sheet"]]
        sheet[parsed["cell"]] = translation

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
