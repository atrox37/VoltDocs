"""Markdown translation parser.

Splits a Markdown document into translatable segments while preserving
structure (headings, paragraphs, list items) and skipping untranslatable
blocks (fenced code blocks, HTML blocks, front-matter).

Each segment carries a ``_md_location`` dict so the exporter can rebuild
the document with translated text in exactly the right place.
"""
from __future__ import annotations

import re

# Matches fenced code blocks (``` or ~~~, optional language tag)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})", re.MULTILINE)
# Matches YAML/TOML front-matter delimiters at the very start of the file
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)
# Text that is purely non-word characters / digits — not worth translating
_NON_TRANSLATABLE_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)
# Markdown inline image / link syntax we preserve verbatim
_INLINE_RE = re.compile(r"!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)|`[^`]+`|<[^>]+>")


def _is_non_translatable(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _NON_TRANSLATABLE_RE.match(stripped):
        return True
    # Pure URL
    if re.match(r"^https?://\S+$", stripped):
        return True
    return False


def _heading_prefix(line: str) -> tuple[str, str]:
    """Return (prefix, text) for a heading line, e.g. ('## ', 'Title')."""
    m = re.match(r"^(#{1,6})\s+", line)
    if m:
        return m.group(0), line[m.end():]
    return "", line


def _list_prefix(line: str) -> tuple[str, str]:
    """Return (prefix, text) for a list item, e.g. ('- ', 'item') or ('1. ', 'item')."""
    m = re.match(r"^(\s*(?:[-*+]|\d+\.)\s+)", line)
    if m:
        return m.group(1), line[m.end():]
    return "", line


def extract_segments(content: bytes) -> list[dict]:
    """Parse Markdown bytes and return a list of translatable segment dicts."""
    text = content.decode("utf-8", errors="replace")

    # ── Strip front-matter (YAML/TOML) ───────────────────────────────────────
    fm_match = _FRONTMATTER_RE.match(text)
    front_matter_end = fm_match.end() if fm_match else 0

    # ── Split into raw lines with their byte-offsets ──────────────────────────
    lines = text.splitlines(keepends=True)

    # Build a map: line_index → char_start_offset
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

        # Skip front-matter lines
        if char_offsets[i] < front_matter_end:
            i += 1
            continue

        # ── Fenced code block detection ───────────────────────────────────────
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

        # ── Blank / horizontal rule / HTML block ──────────────────────────────
        if not stripped or re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            i += 1
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
        list_prefix, text_part = _list_prefix(stripped)
        if list_prefix:
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
                        "prefix": list_prefix,
                    },
                })
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────────────
        if stripped.startswith(">"):
            text_part = re.sub(r"^>\s*", "", stripped)
            if not _is_non_translatable(text_part):
                seg_order = len(segments)
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
                        "prefix": re.match(r"^(>\s*)", stripped).group(1),
                    },
                })
            i += 1
            continue

        # ── Regular paragraph (may span multiple lines) ───────────────────────
        # Collect consecutive non-blank, non-special lines as one paragraph
        para_lines: list[int] = []
        while i < len(lines):
            cur = lines[i].rstrip("\n\r")
            if not cur:
                break
            # Stop at code fence, heading, list item, blockquote
            if _FENCE_RE.match(cur) or re.match(r"^#{1,6}\s", cur) or \
               re.match(r"^\s*(?:[-*+]|\d+\.)\s", cur) or cur.startswith(">"):
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
