from __future__ import annotations

from dataclasses import dataclass

from services.docx_parser import (
    NON_TRANSLATABLE_PATTERN,
    _classify_segment_type,
    _extract_field_display_text,
    _extract_paragraph_text,
    _extract_style_name,
    _is_field_display_paragraph,
    _is_field_paragraph,
    _paragraph_has_drawing,
    _paragraph_is_in_table_cell,
    _paragraph_should_skip_segment,
    _split_multiline_cell_text,
    _parse_xml_bytes,
    _iter_paragraphs,
    is_code_style,
    iter_docx_story_parts,
)


@dataclass
class DocxIrNode:
    id: str
    kind: str
    part_name: str
    paragraph_index: int
    style_name: str | None
    source_text: str
    plain_text: str
    segment_type: str
    line_index: int
    line_count: int
    translate: bool
    has_drawing: bool
    field_display: bool


def _style_key(style_name: str | None) -> str:
    return (style_name or "Normal").strip() or "Normal"


def _node_to_segment(node: DocxIrNode) -> dict:
    order = int(node.id.split("-", 1)[-1]) - 1 if node.id.startswith("seg-") else 0
    segment = {
        "id": node.id,
        "order": order,
        "source_text": node.source_text,
        "plain_text": node.plain_text,
        "style_name": node.style_name,
        "segment_type": node.segment_type,
        "line_index": node.line_index,
        "line_count": node.line_count,
        "_docx_location": {
            "part_name": node.part_name,
            "paragraph_index": node.paragraph_index,
            "field_display": node.field_display,
            "line_index": node.line_index,
            "line_count": node.line_count,
        },
    }
    return segment


def parse_docx_ir(content: bytes) -> dict:
    """Parse a DOCX into a lightweight IR that separates text nodes and assets."""
    story_parts: list[dict] = []
    nodes: list[DocxIrNode] = []
    segments: list[dict] = []
    blocks: list[dict] = []
    assets: list[dict] = []
    styles: dict[str, dict] = {}

    for part_name, xml_bytes in iter_docx_story_parts(content):
        root = _parse_xml_bytes(xml_bytes)
        if root is None:
            continue

        part_nodes: list[dict] = []
        for paragraph_index, paragraph in enumerate(_iter_paragraphs(root)):
            if _is_field_paragraph(paragraph):
                continue

            style_name = _extract_style_name(paragraph)
            has_drawing = _paragraph_has_drawing(paragraph)
            style_id = _style_key(style_name)
            styles.setdefault(
                style_id,
                {
                    "id": style_id,
                    "name": style_name,
                    "kind": "paragraph",
                },
            )

            if _is_field_display_paragraph(paragraph):
                plain_text, source_text = _extract_field_display_text(paragraph)
                if not plain_text:
                    continue
                node_id = f"seg-{len(nodes) + 1}"
                node = DocxIrNode(
                    id=node_id,
                    kind="text",
                    part_name=part_name,
                    paragraph_index=paragraph_index,
                    style_name=style_name,
                    source_text=source_text,
                    plain_text=plain_text,
                    segment_type=_classify_segment_type(style_name, len(nodes), plain_text),
                    line_index=0,
                    line_count=1,
                    translate=True,
                    has_drawing=has_drawing,
                    field_display=True,
                )
                nodes.append(node)
                segment = _node_to_segment(node)
                segments.append(segment)
                block_id = f"block-{len(blocks) + 1}"
                blocks.append(
                    {
                        "id": block_id,
                        "kind": "paragraph",
                        "nodeIds": [node_id],
                        "partName": part_name,
                        "paragraphIndex": paragraph_index,
                        "styleId": style_id,
                        "text": {"source": source_text, "plain": plain_text},
                        "translate": True,
                        "fieldDisplay": True,
                        "assetIds": [],
                    }
                )
                part_nodes.append(
                    {
                        "id": node_id,
                        "kind": node.kind,
                        "text": {"source": source_text, "plain": plain_text},
                        "style": {"name": style_name, "segmentType": node.segment_type},
                        "location": {"paragraphIndex": paragraph_index, "fieldDisplay": True, "lineIndex": 0, "lineCount": 1},
                        "assets": [],
                        "translate": True,
                    }
                )
                if has_drawing:
                    asset_id = f"asset-{len(assets) + 1}"
                    assets.append(
                        {
                            "id": asset_id,
                            "kind": "drawing",
                            "partName": part_name,
                            "paragraphIndex": paragraph_index,
                            "nodeId": node_id,
                        }
                    )
                    blocks[-1]["assetIds"].append(asset_id)
                continue

            plain_text, source_text = _extract_paragraph_text(paragraph)
            if not plain_text or is_code_style(style_name):
                continue
            if _paragraph_should_skip_segment(paragraph, plain_text):
                continue
            if NON_TRANSLATABLE_PATTERN.fullmatch(plain_text):
                continue

            if _paragraph_is_in_table_cell(paragraph):
                line_pairs = _split_multiline_cell_text(plain_text, source_text)
                if len(line_pairs) > 1:
                    for line_index, (line_plain, line_source) in enumerate(line_pairs):
                        node_id = f"seg-{len(nodes) + 1}"
                        node = DocxIrNode(
                            id=node_id,
                            kind="text",
                            part_name=part_name,
                            paragraph_index=paragraph_index,
                            style_name=style_name,
                            source_text=line_source,
                            plain_text=line_plain,
                            segment_type=_classify_segment_type(style_name, len(nodes), line_plain),
                            line_index=line_index,
                            line_count=len(line_pairs),
                            translate=True,
                            has_drawing=has_drawing,
                            field_display=False,
                        )
                        nodes.append(node)
                        segment = _node_to_segment(node)
                        segments.append(segment)
                        blocks.append(
                            {
                                "id": f"block-{len(blocks) + 1}",
                                "kind": "paragraph",
                                "nodeIds": [node_id],
                                "partName": part_name,
                                "paragraphIndex": paragraph_index,
                                "styleId": style_id,
                                "text": {"source": line_source, "plain": line_plain},
                                "translate": True,
                                "fieldDisplay": False,
                                "lineIndex": line_index,
                                "lineCount": len(line_pairs),
                                "assetIds": [],
                            }
                        )
                        part_nodes.append(
                            {
                                "id": node_id,
                                "kind": node.kind,
                                "text": {"source": line_source, "plain": line_plain},
                                "style": {"name": style_name, "segmentType": node.segment_type},
                                "location": {"paragraphIndex": paragraph_index, "lineIndex": line_index, "lineCount": len(line_pairs)},
                                "assets": [],
                                "translate": True,
                            }
                        )
                        if has_drawing:
                            asset_id = f"asset-{len(assets) + 1}"
                            assets.append(
                                {
                                    "id": asset_id,
                                    "kind": "drawing",
                                    "partName": part_name,
                                    "paragraphIndex": paragraph_index,
                                    "nodeId": node_id,
                                }
                            )
                            blocks[-1]["assetIds"].append(asset_id)
                    continue

            node_id = f"seg-{len(nodes) + 1}"
            node = DocxIrNode(
                id=node_id,
                kind="text",
                part_name=part_name,
                paragraph_index=paragraph_index,
                style_name=style_name,
                source_text=source_text,
                plain_text=plain_text,
                segment_type=_classify_segment_type(style_name, len(nodes), plain_text),
                line_index=0,
                line_count=1,
                translate=True,
                has_drawing=has_drawing,
                field_display=False,
            )
            nodes.append(node)
            segment = _node_to_segment(node)
            segments.append(segment)
            block_id = f"block-{len(blocks) + 1}"
            blocks.append(
                {
                    "id": block_id,
                    "kind": "paragraph",
                    "nodeIds": [node_id],
                    "partName": part_name,
                    "paragraphIndex": paragraph_index,
                    "styleId": style_id,
                    "text": {"source": source_text, "plain": plain_text},
                    "translate": True,
                    "fieldDisplay": False,
                    "lineIndex": 0,
                    "lineCount": 1,
                    "assetIds": [],
                }
            )
            part_nodes.append(
                {
                    "id": node_id,
                    "kind": node.kind,
                    "text": {"source": source_text, "plain": plain_text},
                    "style": {"name": style_name, "segmentType": node.segment_type},
                    "location": {"paragraphIndex": paragraph_index, "lineIndex": 0, "lineCount": 1},
                    "assets": [],
                    "translate": True,
                }
            )
            if has_drawing:
                asset_id = f"asset-{len(assets) + 1}"
                assets.append(
                    {
                        "id": asset_id,
                        "kind": "drawing",
                        "partName": part_name,
                        "paragraphIndex": paragraph_index,
                        "nodeId": node_id,
                    }
                )
                blocks[-1]["assetIds"].append(asset_id)

        story_parts.append({"partName": part_name, "nodes": part_nodes})

    return {
        "kind": "docx",
        "version": 1,
        "styles": list(styles.values()),
        "assets": assets,
        "blocks": blocks,
        "storyParts": story_parts,
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind,
                "partName": node.part_name,
                "paragraphIndex": node.paragraph_index,
                "styleName": node.style_name,
                "sourceText": node.source_text,
                "plainText": node.plain_text,
                "segmentType": node.segment_type,
                "lineIndex": node.line_index,
                "lineCount": node.line_count,
                "translate": node.translate,
                "hasDrawing": node.has_drawing,
                "fieldDisplay": node.field_display,
            }
            for node in nodes
        ],
        "segments": segments,
    }


def render_docx_ir(
    original_bytes: bytes,
    ir: dict,
    translated_segments: list[dict],
    target_lang: str = "",
) -> bytes:
    """Render a DOCX IR back into a DOCX using the existing exporter."""
    from services.docx_exporter import export_docx

    return export_docx(original_bytes, ir.get("segments", []), translated_segments, target_lang)
