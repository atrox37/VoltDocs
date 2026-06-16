from services.bedrock import _extract_converse_text, parse_seg_xml


def test_extract_converse_text() -> None:
    response = {
        "output": {
            "message": {
                "content": [{"text": "  Hello world  "}],
            }
        }
    }
    assert _extract_converse_text(response) == "Hello world"


def test_parse_seg_xml() -> None:
    raw = '<seg id="a">One</seg>\n<seg id="b">Two</seg>'
    parsed = parse_seg_xml(raw)
    assert parsed == [{"id": "a", "translation": "One"}, {"id": "b", "translation": "Two"}]
