from __future__ import annotations

from io import BytesIO
import re

import openpyxl


NON_TRANSLATABLE_PATTERN = re.compile(r"[\W\d_]+", re.UNICODE)


def extract_segments(content: bytes) -> list[dict]:
    workbook = openpyxl.load_workbook(BytesIO(content))
    segments: list[dict] = []
    for sheet in workbook.worksheets:
        if sheet.sheet_state != "visible":
            continue
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    continue
                if not isinstance(cell.value, str):
                    continue
                text = cell.value.strip()
                if not text or NON_TRANSLATABLE_PATTERN.fullmatch(text):
                    continue
                segments.append(
                    {
                        "id": f"{sheet.title}_{cell.coordinate}",
                        "order": len(segments),
                        "source_text": cell.value,
                        "plain_text": text,
                        "style_name": sheet.title,
                        "segment_type": "cell",
                        "sheet": sheet.title,
                        "cell": cell.coordinate,
                    }
                )
    return segments
