from pathlib import Path
import zipfile
from lxml import etree

from services.docx.fields import (
    extract_field_title_text,
    is_field_display_paragraph,
    is_toc_field_container,
    replace_field_title_text,
    _title_runs_for_field_display,
)
from services.docx_parser import extract_segments


def test_extract_toc_title_from_hyperlink_paragraph() -> None:
    src = Path("data/uploads/cea524e2_VoltDocsTest.docx")
    if not src.exists():
        return
    root = etree.fromstring(zipfile.ZipFile(src).read("word/document.xml"))
    NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    para = root.xpath(".//w:p", namespaces=NS)[78]
    assert is_field_display_paragraph(para)
    plain, marked = extract_field_title_text(para)
    assert plain.startswith("1.1")
    assert "**" not in plain
    assert plain == marked
    assert "5" not in plain


def test_extract_first_toc_entry_inside_toc_field() -> None:
    """First TOC1 line lives inside the TOC field result (after fldChar separate)."""
    src = Path("data/uploads/cea524e2_VoltDocsTest.docx")
    if not src.exists():
        return
    root = etree.fromstring(zipfile.ZipFile(src).read("word/document.xml"))
    NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    para = root.xpath(".//w:p", namespaces=NS)[77]
    assert is_field_display_paragraph(para)
    assert not is_toc_field_container(para)
    assert len(_title_runs_for_field_display(para)) >= 1
    plain, _ = extract_field_title_text(para)
    assert plain.startswith("1")
    assert "安装" in plain


def test_toc_segments_include_first_entry() -> None:
    src = Path("data/uploads/cea524e2_VoltDocsTest.docx")
    if not src.exists():
        return
    segs = extract_segments(src.read_bytes())
    toc = [s for s in segs if s.get("_docx_location", {}).get("field_display")]
    assert len(toc) == 23
    assert any("安装概况" in s["plain_text"] for s in toc)


def test_replace_field_title_strips_markers() -> None:
    src = Path("data/uploads/cea524e2_VoltDocsTest.docx")
    if not src.exists():
        return
    root = etree.fromstring(zipfile.ZipFile(src).read("word/document.xml"))
    NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    para = root.xpath(".//w:p", namespaces=NS)[78]
    replace_field_title_text(para, "**3. Installation Steps**")
    text = "".join(para.xpath(".//w:t/text()", namespaces=NS))
    assert "**" not in text
    assert "3. Installation Steps" in text
