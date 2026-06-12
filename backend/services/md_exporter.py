"""Markdown translation exporter.

Rebuilds the source Markdown document with each translatable segment
replaced by its translation.  All untranslatable content (code blocks,
front-matter, blank lines, horizontal rules, table separators) is
preserved verbatim.
"""
from __future__ import annotations

import re


def export_md(original_bytes: bytes, parsed_segments: list[dict], request_segments: list[dict]) -> bytes:
    """Return translated Markdown bytes."""
    text = original_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    # ── Build replacement maps ────────────────────────────────────────────────
    # For non-table lines: line_index → full replacement string (or None to delete)
    line_replacements: dict[int, str | None] = {}

    # For table cells: line_index → {cell_index: translation}
    cell_replacements: dict[int, dict[int, str]] = {}

    for parsed, req in zip(parsed_segments, request_segments):
        translation = (
            req.get("translation")
            or req.get("draftTranslation")
            or req.get("draft_translation")
            or ""
        ).strip()
        if not translation:
            continue

        loc = parsed.get("_md_location") or {}
        loc_type = loc.get("type")

        if loc_type in ("heading", "list_item", "blockquote"):
            line_idx: int = loc["line_index"]
            prefix: str = loc["prefix"]
            line_replacements[line_idx] = prefix + translation

        elif loc_type == "paragraph":
            line_indices: list[int] = loc.get("line_indices", [])
            if line_indices:
                line_replacements[line_indices[0]] = translation
                for li in line_indices[1:]:
                    line_replacements[li] = None  # sentinel: delete merged lines

        elif loc_type == "table_cell":
            line_idx = loc["line_index"]
            cell_idx: int = loc["cell_index"]
            if line_idx not in cell_replacements:
                cell_replacements[line_idx] = {}
            cell_replacements[line_idx][cell_idx] = translation

    # ── Rebuild lines ─────────────────────────────────────────────────────────
    out: list[str] = []
    for i, line in enumerate(lines):
        ending = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")

        # Table cell replacement: reconstruct the whole row
        if i in cell_replacements:
            row = line.rstrip("\n\r")
            cells = row.strip("|").split("|")
            replacements_for_row = cell_replacements[i]
            new_cells = []
            for ci, cell in enumerate(cells):
                if ci in replacements_for_row:
                    # Preserve original cell padding
                    lpad = len(cell) - len(cell.lstrip())
                    rpad = len(cell) - len(cell.rstrip())
                    translated = replacements_for_row[ci]
                    new_cells.append(" " * lpad + translated + " " * rpad)
                else:
                    new_cells.append(cell)
            # Reconstruct with leading/trailing | from original
            leading = "|" if row.lstrip().startswith("|") else ""
            trailing = "|" if row.rstrip().endswith("|") else ""
            out.append(leading + "|".join(new_cells) + trailing + ending)
            continue

        # Regular line replacement
        if i in line_replacements:
            if line_replacements[i] is None:
                pass  # deleted (merged paragraph line)
            else:
                out.append(line_replacements[i] + ending)
            continue

        # No replacement — keep verbatim
        out.append(line)

    return "".join(out).encode("utf-8")
