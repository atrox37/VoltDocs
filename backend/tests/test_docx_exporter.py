from __future__ import annotations

from io import BytesIO
import zipfile

from docx import Document
from docx.shared import Inches
from PIL import Image

from services.docx_exporter import export_docx
from services.docx_parser import extract_segments


def _make_docx_with_inline_image() -> bytes:
    image_buffer = BytesIO()
    Image.new("RGB", (24, 24), color=(255, 0, 0)).save(image_buffer, format="PNG")
    image_buffer.seek(0)

    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run("Step 1 ")
    paragraph.add_run().add_picture(image_buffer, width=Inches(0.25))
    paragraph.add_run(" install bracket")

    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def _document_xml(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as archive:
        return archive.read("word/document.xml").decode("utf-8", errors="ignore")


def test_export_docx_preserves_inline_drawings_when_replacing_text() -> None:
    original = _make_docx_with_inline_image()
    segments = extract_segments(original)
    assert len(segments) == 1

    translated = export_docx(
        original,
        segments,
        [{"translation": "Step One install bracket translated"}],
    )

    original_xml = _document_xml(original)
    translated_xml = _document_xml(translated)

    assert original_xml.count("<w:drawing") == 1
    assert translated_xml.count("<w:drawing") == 1
    assert "Step One install bracket translated" in translated_xml
