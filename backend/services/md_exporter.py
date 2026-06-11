"""Markdown translation exporter.

Rebuilds the source Markdown document with each translatable segment
replaced by its translation.  All untranslatable content (code blocks,
front-matter, blank lines, horizontal rules) is preserved verbatim.
"""
from __future__ import annotations


def export_md(original_bytes: bytes, parsed_segments: list[dict], request_segments: list[dict]) -> bytes:
    """Return translated Markdown bytes.

    Args:
        original_bytes:   Raw bytes of the source .md file.
        parsed_segments:  Segment dicts from md_parser.extract_segments().
        request_segments: Dicts with "translation" / "draftTranslation" /
                          "draft_translation" keys aligned with parsed_segments.
    """
    # Build replacement map: line_index (or first line of paragraph) → translated text
    replacements: dict[int, str] = {}

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
            replacements[line_idx] = prefix + translation

        elif loc_type == "paragraph":
            line_indices: list[int] = loc.get("line_indices", [])
            if line_indices:
                # Replace the first line with translated text, mark the rest for deletion
                replacements[line_indices[0]] = translation
                for li in line_indices[1:]:
                    replacements[li] = None  # type: ignore[assignment]  # sentinel: delete

    text = original_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    out: list[str] = []
    for i, line in enumerate(lines):
        if i not in replacements:
            out.append(line)
        elif replacements[i] is None:
            # Extra paragraph lines that are now merged into the first → skip
            pass
        else:
            # Preserve original line ending
            ending = ""
            if line.endswith("\r\n"):
                ending = "\r\n"
            elif line.endswith("\n"):
                ending = "\n"
            out.append(replacements[i] + ending)

    return "".join(out).encode("utf-8")
