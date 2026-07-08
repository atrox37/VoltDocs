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


def test_parse_seg_xml_strips_placeholder_leakage() -> None:
    raw = '<seg id="a"><translated text></seg>\n<seg id="b">Actual translation</seg>'
    parsed = parse_seg_xml(raw)
    assert parsed == [{"id": "b", "translation": "Actual translation"}]
