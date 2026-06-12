"""Markdown translation parser.

Splits a Markdown document into translatable segments while preserving
structure (headings, paragraphs, list items, tables) and skipping
untranslatable blocks (fenced code blocks, HTML blocks, front-matter,
horizontal rules, table separator rows, pure-symbol lines).

Each segment carries a ``_md_location`` dict so the exporter can rebuild
the document with translated text in exactly the right place.
"""
from __future__ import annotations

import re

# Matches fenced code blocks (``` or ~~~, optional language tag)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
# Matches YAML/TOML front-matter delimiters at the very start of the file
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)
# Text that is purely non-word characters / digits — not worth translating
_NON_TRANSLATABLE_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)
# Horizontal rules: three or more -, *, or _ optionally with spaces
_HR_RE = re.compile(r"^\s*([*\-_])\s*(?:\1\s*){2,}$")
# Table row: starts and ends with | (may have leading spaces)
_TABLE_ROW_RE = re.compile(r"^\s*\|")
# Table separator row: only |, -, :, space
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
# HTML block or inline HTML tag on its own line
_HTML_LINE_RE = re.compile(r"^\s*<[a-zA-Z/!]")


def _is_non_translatable(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _NON_TRANSLATABLE_RE.match(stripped):
        return True
    # Pure URL
    if re.match(r"^https?://\S+$", stripped):
        return True
    # Horizontal rule
    if _HR_RE.match(stripped):
        return True
    return False


def _heading_prefix(line: str) -> tuple[str, str]:
    m = re.match(r"^(#{1,6})\s+", line)
    if m:
        return m.group(0), line[m.end():]
    return "", line


def _list_prefix(line: str) -> tuple[str, str]:
    m = re.match(r"^(\s*(?:[-*+]|\d+\.)\s+)", line)
    if m:
        return m.group(1), line[m.end():]
    return "", line


def _is_paragraph_break(line: str) -> bool:
    """Return True if this line should stop a paragraph accumulation."""
    stripped = line.rstrip("\n\r")
    if not stripped:
        return True
    if _FENCE_RE.match(stripped):
        return True
    if re.match(r"^#{1,6}\s", stripped):
        return True
    if re.match(r"^\s*(?:[-*+]|\d+\.)\s", stripped):
        return True
    if stripped.startswith(">"):
        return True
    if _TABLE_ROW_RE.match(stripped):
        return True
    if _HR_RE.match(stripped):
        return True
    return False


def extract_segments(content: bytes) -> list[dict]:
    """Parse Markdown bytes and return a list of translatable segment dicts."""
    text = content.decode("utf-8", errors="replace")

    # ── Front-matter ──────────────────────────────────────────────────────────
    fm_match = _FRONTMATTER_RE.match(text)
    front_matter_end = fm_match.end() if fm_match else 0

    lines = text.splitlines(keepends=True)

    # Build char-offset map for front-matter check
    char_offsets: list[int] = []
    offset = 0
    for line in lines:
        char_offsets.append(offset)
        offset += len(line)

    segments: list[dict] = []
    in_code_block = False
    code_fence_char: str = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\n\r")

        # Skip front-matter
        if char_offsets[i] < front_matter_end:
            i += 1
            continue

        # ── Fenced code block ─────────────────────────────────────────────────
        fence_m = _FENCE_RE.match(stripped)
        if fence_m:
            fence_char = fence_m.group(1)[0]
            if not in_code_block:
                in_code_block = True
                code_fence_char = fence_char
            elif fence_char == code_fence_char:
                in_code_block = False
            i += 1
            continue

        if in_code_block:
            i += 1
            continue

        # ── Blank line ────────────────────────────────────────────────────────
        if not stripped:
            i += 1
            continue

        # ── Horizontal rule (---, ***, ___) ───────────────────────────────────
        if _HR_RE.match(stripped):
            i += 1
            continue

        # ── HTML block lines (skip, don't translate) ──────────────────────────
        if _HTML_LINE_RE.match(stripped):
            i += 1
            continue

        # ── Table ─────────────────────────────────────────────────────────────
        if _TABLE_ROW_RE.match(stripped):
            # Collect all contiguous table rows
            table_start = i
            table_lines: list[int] = []
            while i < len(lines):
                cur = lines[i].rstrip("\n\r")
                if not _TABLE_ROW_RE.match(cur):
                    break
                table_lines.append(i)
                i += 1
            # Translate each data row individually (skip separator rows)
            for li in table_lines:
                row = lines[li].rstrip("\n\r")
                if _TABLE_SEP_RE.match(row):
                    continue  # separator row — skip
                # Extract cell texts, skip empty cells
                cells = [c.strip() for c in row.strip("|").split("|")]
                translated_cells: list[str] = []
                for cell_idx, cell in enumerate(cells):
                    if not cell or _is_non_translatable(cell):
                        translated_cells.append(None)
                        continue
                    seg_order = len(segments)
                    segments.append({
                        "id": f"seg-{seg_order + 1}",
                        "order": seg_order,
                        "source_text": cell,
                        "plain_text": cell,
                        "style_name": "table_cell",
                        "segment_type": "paragraph",
                        "_md_location": {
                            "type": "table_cell",
                            "line_index": li,
                            "cell_index": cell_idx,
                            "original_row": row,
                        },
                    })
                    translated_cells.append(seg_order)
            continue

        # ── Heading ───────────────────────────────────────────────────────────
        prefix, text_part = _heading_prefix(stripped)
        if prefix:
            if not _is_non_translatable(text_part):
                seg_order = len(segments)
                segments.append({
                    "id": f"seg-{seg_order + 1}",
                    "order": seg_order,
                    "source_text": text_part.strip(),
                    "plain_text": text_part.strip(),
                    "style_name": f"heading{len(prefix.rstrip())}",
                    "segment_type": "title",
                    "_md_location": {
                        "type": "heading",
                        "line_index": i,
                        "prefix": prefix,
                    },
                })
            i += 1
            continue

        # ── List item ─────────────────────────────────────────────────────────
        list_pfx, text_part = _list_prefix(stripped)
        if list_pfx:
            if not _is_non_translatable(text_part):
                seg_order = len(segments)
                segments.append({
                    "id": f"seg-{seg_order + 1}",
                    "order": seg_order,
                    "source_text": text_part.strip(),
                    "plain_text": text_part.strip(),
                    "style_name": "list",
                    "segment_type": "paragraph",
                    "_md_location": {
                        "type": "list_item",
                        "line_index": i,
                        "prefix": list_pfx,
                    },
                })
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────────────
        if stripped.startswith(">"):
            text_part = re.sub(r"^>\s*", "", stripped)
            if not _is_non_translatable(text_part):
                seg_order = len(segments)
                bq_m = re.match(r"^(>\s*)", stripped)
                segments.append({
                    "id": f"seg-{seg_order + 1}",
                    "order": seg_order,
                    "source_text": text_part.strip(),
                    "plain_text": text_part.strip(),
                    "style_name": "blockquote",
                    "segment_type": "paragraph",
                    "_md_location": {
                        "type": "blockquote",
                        "line_index": i,
                        "prefix": bq_m.group(1) if bq_m else "> ",
                    },
                })
            i += 1
            continue

        # ── Regular paragraph ─────────────────────────────────────────────────
        # Collect consecutive non-break lines as one paragraph
        para_lines: list[int] = []
        while i < len(lines):
            cur = lines[i].rstrip("\n\r")
            if _is_paragraph_break(lines[i]):
                break
            para_lines.append(i)
            i += 1

        if not para_lines:
            i += 1
            continue

        full_text = " ".join(lines[li].rstrip("\n\r") for li in para_lines).strip()
        if _is_non_translatable(full_text):
            continue

        seg_order = len(segments)
        segments.append({
            "id": f"seg-{seg_order + 1}",
            "order": seg_order,
            "source_text": full_text,
            "plain_text": full_text,
            "style_name": "paragraph",
            "segment_type": "paragraph",
            "_md_location": {
                "type": "paragraph",
                "line_indices": para_lines,
            },
        })

    return segments
