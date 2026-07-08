from services.bedrock import parse_seg_xml
from services.docx.markup import clean_translation_artifacts, normalize_adjacent_bold_markers
from services.docx.fields import strip_toc_page_suffix
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


def test_clean_translation_artifacts_strips_seg_tag() -> None:
    raw = '<seg id="seg-273">3.3 Step 3,   Assembling the Fixed Frame and Combination Frame。'
    assert clean_translation_artifacts(raw, target_lang="en-US") == (
        "3.3 Step 3, Assembling the Fixed Frame and Combination Frame."
    )


def test_clean_translation_artifacts_strips_placeholder_leakage() -> None:
    assert clean_translation_artifacts("<translated text>", target_lang="en-US") == ""


def test_parse_seg_xml_cleans_json_translation_with_seg_echo() -> None:
    raw = '{"id": "seg-273", "translation": "<seg id=\\"seg-273\\">Hello</seg>"}'
    parsed = parse_seg_xml(raw, target_lang="en-US")
    assert parsed == [{"id": "seg-273", "translation": "Hello"}]


def test_normalize_adjacent_bold_markers() -> None:
    marked = "**3.3步骤3****组装固定框架**"
    assert normalize_adjacent_bold_markers(marked) == "**3.3步骤3** **组装固定框架**"


def test_strip_toc_page_suffix() -> None:
    xml = (
        f'<w:p xmlns:w="{W_NS}">'
        "<w:r><w:t>Title text</w:t></w:r>"
        "<w:r><w:t>22</w:t></w:r>"
        "</w:p>"
    )
    para = etree.fromstring(xml)
    assert strip_toc_page_suffix("Title text22", para) == "Title text"
    assert strip_toc_page_suffix("Step 3", para) == "Step 3"
