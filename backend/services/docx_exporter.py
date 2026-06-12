from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
import zipfile

from lxml import etree

from services.docx_parser import NSMAP, W_NS, iter_docx_story_parts, _RECOVER_PARSER


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


def _child_has_translatable_text(child: etree._Element) -> bool:
    return bool(child.xpath(".//w:t | .//w:tab | .//w:br | .//w:cr", namespaces=NSMAP))


def _run_has_payload(run: etree._Element) -> bool:
    return any(grandchild.tag != f"{{{W_NS}}}rPr" for grandchild in run)


def _clone_preserving_non_text_content(child: etree._Element) -> etree._Element | None:
    clone = deepcopy(child)

    for node in clone.xpath(".//w:t | .//w:tab | .//w:br | .//w:cr", namespaces=NSMAP):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)

    for run in list(clone.xpath(".//w:r", namespaces=NSMAP)):
        if not _run_has_payload(run):
            parent = run.getparent()
            if parent is not None:
                parent.remove(run)

    for hyperlink in list(clone.xpath(".//w:hyperlink", namespaces=NSMAP)):
        has_runs = bool(hyperlink.xpath("./w:r", namespaces=NSMAP))
        has_non_run_children = any(grandchild.tag != f"{{{W_NS}}}r" for grandchild in hyperlink)
        if not has_runs and not has_non_run_children:
            parent = hyperlink.getparent()
            if parent is not None:
                parent.remove(hyperlink)

    if clone.tag == f"{{{W_NS}}}r" and not _run_has_payload(clone):
        return None
    if clone.tag == f"{{{W_NS}}}hyperlink" and not list(clone):
        return None
    return clone


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
    parts = _parse_inline_format_markers(translation) or [(translation, False, False, False)]
    new_children: list[etree._Element] = []
    inserted_translation = False
    template_index = 0

    for child in list(paragraph):
        if child.tag == f"{{{W_NS}}}pPr":
            new_children.append(deepcopy(child))
            continue

        has_text = _child_has_translatable_text(child)
        if has_text and not inserted_translation:
            for text, bold, italic, strike in parts:
                if not text:
                    continue
                template = templates[min(template_index, len(templates) - 1)]
                new_children.append(_make_run(text, template, bold, italic, strike))
                template_index += 1
            inserted_translation = True

        preserved = _clone_preserving_non_text_content(child) if has_text else deepcopy(child)
        if preserved is not None:
            new_children.append(preserved)

    if not inserted_translation:
        for text, bold, italic, strike in parts:
            if not text:
                continue
            template = templates[min(template_index, len(templates) - 1)]
            new_children.append(_make_run(text, template, bold, italic, strike))
            template_index += 1

    for child in list(paragraph):
        paragraph.remove(child)
    for child in new_children:
        paragraph.append(child)


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

    binary_exts = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
        ".emf", ".wmf", ".svg", ".ico", ".webp",
        ".bin", ".dat",
    }

    with zipfile.ZipFile(input_buffer, "r") as source_archive, zipfile.ZipFile(output_buffer, "w") as target_archive:
        story_parts = {name: data for name, data in iter_docx_story_parts(original_bytes)}

        for entry in source_archive.infolist():
            raw = source_archive.read(entry.filename)
            name_lower = entry.filename.lower()
            ext = "." + name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
            compress_type = zipfile.ZIP_STORED if ext in binary_exts else zipfile.ZIP_DEFLATED

            if entry.filename in story_parts:
                try:
                    root = etree.fromstring(raw)
                except etree.XMLSyntaxError:
                    try:
                        root = etree.fromstring(raw, _RECOVER_PARSER)
                    except Exception:
                        target_archive.writestr(entry, raw, compress_type=compress_type)
                        continue
                paragraphs = root.xpath(".//w:p", namespaces=NSMAP)
                for index, paragraph in enumerate(paragraphs):
                    translation = replacements.get((entry.filename, index))
                    if translation:
                        _replace_paragraph_runs(paragraph, translation)
                raw = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
                target_archive.writestr(entry, raw, compress_type=zipfile.ZIP_DEFLATED)
            else:
                target_archive.writestr(entry, raw, compress_type=compress_type)

    return output_buffer.getvalue()
