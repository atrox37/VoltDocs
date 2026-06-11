from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
import zipfile

from lxml import etree

from services.docx_parser import NSMAP, W_NS, iter_docx_story_parts


@dataclass
class RunTemplate:
    rpr: etree._Element | None


def _parse_inline_format_markers(text: str) -> list[tuple[str, bool, bool, bool]]:
    parts: list[tuple[str, bool, bool, bool]] = []
    current: list[str] = []
    bold = False
    italic = False
    strike = False
    i = 0
    while i < len(text):
        if text.startswith("~~", i):
            if current:
                parts.append(("".join(current), bold, italic, strike))
                current = []
            strike = not strike
            i += 2
            continue
        if text.startswith("***", i):
            if current:
                parts.append(("".join(current), bold, italic, strike))
                current = []
            bold = not bold
            italic = not italic
            i += 3
            continue
        if text.startswith("**", i):
            if current:
                parts.append(("".join(current), bold, italic, strike))
                current = []
            bold = not bold
            i += 2
            continue
        if text.startswith("*", i):
            if current:
                parts.append(("".join(current), bold, italic, strike))
                current = []
            italic = not italic
            i += 1
            continue
        current.append(text[i])
        i += 1
    if current:
        parts.append(("".join(current), bold, italic, strike))
    return parts


def _capture_run_templates(paragraph: etree._Element) -> list[RunTemplate]:
    templates: list[RunTemplate] = []
    for run in paragraph.xpath("./w:r", namespaces=NSMAP):
        rpr = run.find("./w:rPr", namespaces=NSMAP)
        templates.append(RunTemplate(rpr=deepcopy(rpr) if rpr is not None else None))
    if not templates:
        templates.append(RunTemplate(rpr=None))
    return templates


_PRESERVE_TAGS = {
    # 嵌入式图片
    f"{{{W_NS}}}drawing",
    # 浮动图片（Word 2007 兼容层）
    "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent",
    # 表格（段落不应包含表格，但防御性保留）
    f"{{{W_NS}}}tbl",
    # 书签
    f"{{{W_NS}}}bookmarkStart",
    f"{{{W_NS}}}bookmarkEnd",
    # 复杂域
    f"{{{W_NS}}}fldSimple",
    # SDT 内容控件
    f"{{{W_NS}}}sdt",
}


def _remove_non_property_children(paragraph: etree._Element) -> None:
    """移除段落中的 run 等可替换元素，但保留图片、书签等结构性元素。"""
    for child in list(paragraph):
        if child.tag == f"{{{W_NS}}}pPr":
            continue  # 保留段落属性
        if child.tag in _PRESERVE_TAGS:
            continue  # 保留图片、书签等
        paragraph.remove(child)


def _ensure_format_flags(rpr: etree._Element, bold: bool, italic: bool, strike: bool) -> None:
    for tag_name, enabled in (("b", bold), ("i", italic), ("strike", strike)):
        full_tag = f"{{{W_NS}}}{tag_name}"
        existing = rpr.find(f"./w:{tag_name}", namespaces=NSMAP)
        if enabled and existing is None:
            etree.SubElement(rpr, full_tag)
        if not enabled and existing is not None:
            rpr.remove(existing)


def _make_run(text: str, template: RunTemplate, bold: bool, italic: bool, strike: bool) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    rpr = deepcopy(template.rpr) if template.rpr is not None else etree.Element(f"{{{W_NS}}}rPr")
    _ensure_format_flags(rpr, bold, italic, strike)
    if len(rpr) > 0 or rpr.attrib:
        run.append(rpr)
    text_node = etree.SubElement(run, f"{{{W_NS}}}t")
    if text.startswith(" ") or text.endswith(" ") or "\n" in text or "\t" in text:
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text
    return run


def _replace_paragraph_runs(paragraph: etree._Element, translation: str) -> None:
    templates = _capture_run_templates(paragraph)
    _remove_non_property_children(paragraph)
    parts = _parse_inline_format_markers(translation) or [(translation, False, False, False)]
    template_index = 0
    for text, bold, italic, strike in parts:
        if not text:
            continue
        template = templates[min(template_index, len(templates) - 1)]
        paragraph.append(_make_run(text, template, bold, italic, strike))
        template_index += 1


def export_docx(original_bytes: bytes, parsed_segments: list[dict], request_segments: list[dict]) -> bytes:
    replacements: dict[tuple[str, int], str] = {}
    for parsed, request in zip(parsed_segments, request_segments):
        translation = (request.get("translation") or request.get("draftTranslation") or request.get("draft_translation") or "").strip()
        if not translation:
            continue
        location = parsed.get("_docx_location") or {}
        key = (location.get("part_name"), location.get("paragraph_index"))
        replacements[key] = translation

    input_buffer = BytesIO(original_bytes)
    output_buffer = BytesIO()

    with zipfile.ZipFile(input_buffer, "r") as source_archive, zipfile.ZipFile(output_buffer, "w", zipfile.ZIP_DEFLATED) as target_archive:
        story_parts = {name: data for name, data in iter_docx_story_parts(original_bytes)}

        for entry in source_archive.infolist():
            raw = source_archive.read(entry.filename)
            if entry.filename in story_parts:
                root = etree.fromstring(raw)
                paragraphs = root.xpath(".//w:p", namespaces=NSMAP)
                for index, paragraph in enumerate(paragraphs):
                    translation = replacements.get((entry.filename, index))
                    if translation:
                        _replace_paragraph_runs(paragraph, translation)
                raw = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
            target_archive.writestr(entry, raw)

    return output_buffer.getvalue()
