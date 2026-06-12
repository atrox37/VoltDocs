from __future__ import annotations

from io import BytesIO
import re
import zipfile

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}
XML_NAMESPACES = {"w": W_NS}
CODE_STYLES = {"sourcecode", "verbatim", "preformatted", "pre", "code"}
NON_TRANSLATABLE_PATTERN = re.compile(r"[\W\d_]+", re.UNICODE)


def strip_inline_markers(text: str) -> str:
    return re.sub(r"(\*\*|\*|~~)", "", text)


def is_code_style(style_name: str | None) -> bool:
    normalized = (style_name or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    return normalized in CODE_STYLES or normalized.startswith("sourcecode")


def iter_docx_story_parts(content: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        story_names = ["word/document.xml"]
        story_names.extend(sorted(name for name in names if re.fullmatch(r"word/header\d+\.xml", name)))
        story_names.extend(sorted(name for name in names if re.fullmatch(r"word/footer\d+\.xml", name)))
        parts: list[tuple[str, bytes]] = []
        for name in story_names:
            try:
                parts.append((name, archive.read(name)))
            except KeyError:
                continue
        return parts


def _iter_paragraphs(root: etree._Element) -> list[etree._Element]:
    return root.xpath(".//w:p", namespaces=NSMAP)


def _extract_style_name(paragraph: etree._Element) -> str | None:
    style = paragraph.find("./w:pPr/w:pStyle", namespaces=NSMAP)
    if style is None:
        return None
    return style.get(f"{{{W_NS}}}val") or style.get("val")


def _extract_run_text(run: etree._Element) -> str:
    parts: list[str] = []
    for child in run.xpath("./w:t | ./w:tab | ./w:br | ./w:cr", namespaces=NSMAP):
        tag = child.tag
        if tag == f"{{{W_NS}}}t":
            parts.append(child.text or "")
        elif tag == f"{{{W_NS}}}tab":
            parts.append("\t")
        elif tag in {f"{{{W_NS}}}br", f"{{{W_NS}}}cr"}:
            parts.append("\n")
    return "".join(parts)


def _extract_paragraph_text(paragraph: etree._Element) -> tuple[str, str]:
    plain_parts: list[str] = []
    marked_parts: list[str] = []
    runs = paragraph.xpath("./w:r | ./w:hyperlink//w:r", namespaces=NSMAP)
    for run in runs:
        text = _extract_run_text(run)
        if not text:
            continue
        plain_parts.append(text)

        marked = text
        rpr = run.find("./w:rPr", namespaces=NSMAP)
        is_bold = rpr is not None and rpr.find("./w:b", namespaces=NSMAP) is not None
        is_italic = rpr is not None and rpr.find("./w:i", namespaces=NSMAP) is not None
        is_strike = rpr is not None and rpr.find("./w:strike", namespaces=NSMAP) is not None

        if is_bold and is_italic:
            marked = f"***{marked}***"
        elif is_bold:
            marked = f"**{marked}**"
        elif is_italic:
            marked = f"*{marked}*"
        if is_strike:
            marked = f"~~{marked}~~"
        marked_parts.append(marked)
    return "".join(plain_parts).strip(), "".join(marked_parts).strip()


def _classify_segment_type(style_name: str | None, order: int, plain_text: str) -> str:
    if (style_name and ("heading" in style_name.lower() or "title" in style_name.lower())) or (order == 0 and len(plain_text) <= 30):
        return "title"
    return "paragraph"


_RECOVER_PARSER = etree.XMLParser(recover=True, remove_blank_text=True)


def _parse_xml_bytes(xml_bytes: bytes) -> etree._Element | None:
    """解析 DOCX 内部 XML，优先严格模式，失败后自动切换到容错模式。"""
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        try:
            # recover=True 会尽量修复不匹配的标签并返回尽可能完整的树
            return etree.fromstring(xml_bytes, _RECOVER_PARSER)
        except Exception:
            return None


def extract_segments(content: bytes) -> list[dict]:
    segments: list[dict] = []
    for part_name, xml_bytes in iter_docx_story_parts(content):
        root = _parse_xml_bytes(xml_bytes)
        if root is None:
            continue
        paragraphs = _iter_paragraphs(root)
        for paragraph_index, paragraph in enumerate(paragraphs):
            style_name = _extract_style_name(paragraph)
            plain_text, source_text = _extract_paragraph_text(paragraph)
            if not plain_text or is_code_style(style_name):
                continue
            if NON_TRANSLATABLE_PATTERN.fullmatch(plain_text):
                continue

            segment_order = len(segments)
            segments.append(
                {
                    "id": f"seg-{segment_order + 1}",
                    "order": segment_order,
                    "source_text": source_text,
                    "plain_text": plain_text,
                    "style_name": style_name,
                    "segment_type": _classify_segment_type(style_name, segment_order, plain_text),
                    "_docx_location": {
                        "part_name": part_name,
                        "paragraph_index": paragraph_index,
                    },
                }
            )
    return segments
