"""Word field / TOC helpers — extract and replace visible title text only."""
from __future__ import annotations

import re

from lxml import etree

from services.docx.markup import strip_inline_markers

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


def _run_text(run: etree._Element) -> str:
    parts: list[str] = []
    for child in run.xpath("./w:t | ./w:tab", namespaces=NSMAP):
        tag = child.tag
        if tag == f"{{{W_NS}}}t":
            parts.append(child.text or "")
        elif tag == f"{{{W_NS}}}tab":
            parts.append("\t")
    return "".join(parts)


def _paragraph_instr(paragraph: etree._Element) -> str:
    return "".join(paragraph.xpath(".//w:instrText/text()", namespaces=NSMAP))


def _has_toc_anchor(paragraph: etree._Element) -> bool:
    for anchor in paragraph.xpath(".//w:hyperlink/@w:anchor", namespaces=NSMAP):
        if str(anchor).startswith("_Toc"):
            return True
    return bool(re.search(r'HYPERLINK\s+\\l\s+"_Toc', _paragraph_instr(paragraph)))


def _toc_style_name(paragraph: etree._Element) -> str | None:
    style = paragraph.find("./w:pPr/w:pStyle", namespaces=NSMAP)
    if style is None:
        return None
    return style.get(f"{{{W_NS}}}val") or style.get("val")


def is_toc_field_container(paragraph: etree._Element) -> bool:
    """Paragraph that only carries the TOC field instruction (no entry title)."""
    instr = _paragraph_instr(paragraph).strip()
    if not instr.upper().startswith("TOC"):
        return False
    return not _has_toc_anchor(paragraph) and "PAGEREF" not in instr


def is_field_display_paragraph(paragraph: etree._Element) -> bool:
    """TOC entry — translate visible title, keep page-number PAGEREF field."""
    if is_toc_field_container(paragraph):
        return False

    instr = _paragraph_instr(paragraph)
    if "PAGEREF" in instr:
        return True

    style = (_toc_style_name(paragraph) or "").lower()
    if "toc" in style and _has_toc_anchor(paragraph):
        return True

    if re.search(r'HYPERLINK\s+\\l\s+"_Toc', instr):
        return True

    return False


def is_skippable_field_paragraph(paragraph: etree._Element) -> bool:
    """Non-TOC fields (plain HYPERLINK etc.) — leave untouched."""
    if not paragraph.xpath(".//w:fldChar | .//w:instrText", namespaces=NSMAP):
        return False
    return not is_field_display_paragraph(paragraph)


def _pageref_block_start_index(runs: list[etree._Element]) -> int | None:
    """Index of the first run in the trailing PAGEREF page-number field."""
    for i in range(len(runs) - 1, -1, -1):
        instr = "".join(runs[i].xpath(".//w:instrText/text()", namespaces=NSMAP))
        if "PAGEREF" not in instr:
            continue
        start = i
        while start > 0:
            prev = runs[start - 1]
            if prev.xpath("./w:fldChar[@w:fldCharType='begin']", namespaces=NSMAP):
                start -= 1
                break
            if prev.xpath("./w:instrText", namespaces=NSMAP) or prev.xpath("./w:fldChar", namespaces=NSMAP):
                start -= 1
                continue
            break
        return start
    return None


def _is_non_title_run(run: etree._Element) -> bool:
    if run.xpath("./w:instrText", namespaces=NSMAP):
        return True
    if run.xpath("./w:fldChar", namespaces=NSMAP) and not run.xpath("./w:t", namespaces=NSMAP):
        return True
    text = _run_text(run)
    return not text or text == "\t"


def _title_runs_for_field_display(paragraph: etree._Element) -> list[etree._Element]:
    """Visible title runs — includes text inside TOC field result, excludes PAGEREF block."""
    runs = paragraph.xpath(".//w:r", namespaces=NSMAP)
    pageref_start = _pageref_block_start_index(runs)
    end = pageref_start if pageref_start is not None else len(runs)

    title_runs: list[etree._Element] = []
    for run in runs[:end]:
        if _is_non_title_run(run):
            continue
        title_runs.append(run)
    return title_runs


# Backward-compatible alias used in tests / diagnostics
_title_runs_before_field = _title_runs_for_field_display


def extract_field_title_text(paragraph: etree._Element) -> tuple[str, str]:
    """Return plain title for a TOC/PAGEREF paragraph (no inline markers)."""
    plain_parts: list[str] = []
    for run in _title_runs_for_field_display(paragraph):
        text = _run_text(run)
        if text.strip():
            plain_parts.append(text)
    plain = "".join(plain_parts).strip()
    return plain, plain


def _visible_page_number(paragraph: etree._Element) -> str | None:
    nums = [t.strip() for t in paragraph.xpath(".//w:t/text()", namespaces=NSMAP) if t.strip().isdigit()]
    return nums[-1] if nums else None


def strip_toc_page_suffix(translation: str, paragraph: etree._Element) -> str:
    """Remove a glued TOC page number when the model appended it to the title."""
    page = _visible_page_number(paragraph)
    if not page or not translation.rstrip().endswith(page):
        return translation
    before = translation.rstrip()[:- len(page)]
    if before and before[-1] not in " \t":
        return before.rstrip()
    return translation


def replace_field_title_text(paragraph: etree._Element, translation: str) -> None:
    """Replace only the TOC title run(s); preserve tab + PAGEREF page-number field."""
    translation = strip_inline_markers(translation).strip()
    translation = strip_toc_page_suffix(translation, paragraph)
    if not translation:
        return
    title_runs = _title_runs_for_field_display(paragraph)
    if not title_runs:
        return

    first = title_runs[0]
    t_nodes = first.xpath("./w:t", namespaces=NSMAP)
    if not t_nodes:
        t_node = etree.SubElement(first, f"{{{W_NS}}}t")
    else:
        t_node = t_nodes[0]
    if translation.startswith(" ") or translation.endswith(" "):
        t_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t_node.text = translation

    for extra in title_runs[1:]:
        parent = extra.getparent()
        if parent is not None:
            parent.remove(extra)
