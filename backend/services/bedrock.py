"""Direct AWS Bedrock translation via the unified Converse API.

Supports Amazon Nova, Anthropic Claude, Meta Llama, Mistral, and other
Bedrock text models through a single request/response shape.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="bedrock")

_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "TooManyRequestsException",
    "RequestTimeout",
    "RequestThrottled",
    "ModelNotReadyException",
}

_SEG_RE = re.compile(r'<seg\s+id="([^"]+)">([\s\S]*?)</seg>')

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_SHORT_SEGMENT_MAX_LEN = 6


def _build_client(region: str, profile: str | None) -> "boto3.client":
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client("bedrock-runtime", region_name=region)


def _extract_converse_text(response: dict) -> str:
    message = (response.get("output") or {}).get("message") or {}
    parts: list[str] = []
    for block in message.get("content") or []:
        text = block.get("text")
        if text:
            parts.append(text)
    raw = "".join(parts).strip()
    if not raw:
        raise RuntimeError("Empty response from Bedrock Converse")
    return raw


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in _RETRYABLE_ERROR_CODES
    name = type(exc).__name__
    return name in _RETRYABLE_ERROR_CODES or "Timeout" in name or "Throttl" in name


def _converse_sync(
    client,
    model_id: str,
    system_prompt: str,
    user_message: str,
    *,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> str:
    kwargs: dict = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": user_message}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system_prompt.strip():
        kwargs["system"] = [{"text": system_prompt}]

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            delay = _BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "Bedrock Converse retry %d/%d in %.1fs (model=%s error: %s)",
                attempt, _MAX_RETRIES - 1, delay, model_id, last_exc,
            )
            time.sleep(delay)
        try:
            return _extract_converse_text(client.converse(**kwargs))
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                raise
    raise last_exc  # type: ignore[misc]


def parse_seg_xml(raw_text: str, *, target_lang: str = "") -> list[dict]:
    from services.docx.markup import clean_translation_artifacts

    def _clean(translation: str) -> str:
        return clean_translation_artifacts(translation.strip(), target_lang=target_lang)

    results = [
        {"id": match.group(1), "translation": _clean(match.group(2))}
        for match in _SEG_RE.finditer(raw_text)
    ]
    if results:
        return results

    loose: list[dict] = []
    for match in re.finditer(r'<seg\s+id="([^"]+)">([\s\S]*?)(?:</seg>|(?=<seg\s+id=)|$)', raw_text, re.IGNORECASE):
        translation = _clean(match.group(2))
        if translation:
            loose.append({"id": match.group(1), "translation": translation})
    if loose:
        return loose

    json_results: list[dict] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            mobj = re.search(r"\{[^{}]*\}", line)
            if mobj:
                line = mobj.group(0)
            else:
                continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("id"):
            json_results.append({
                "id": str(item["id"]),
                "translation": clean_translation_artifacts(
                    str(item.get("translation", "")).strip(),
                    target_lang=target_lang,
                ),
            })
    return json_results


def _build_system_prompt(
    glossary: list[dict],
    source_lang: str,
    target_lang: str,
) -> str:
    is_zh_to_en = source_lang.startswith("zh") and target_lang.startswith("en")
    direction = "Chinese text into English" if is_zh_to_en else "English text into Chinese"

    glossary_lines = [
        f"- {item['source']} → {item['target']}"
        + (f"  [context: {item['context']}]" if item.get("context") else "")
        for item in glossary
    ]
    glossary_section = ""
    if glossary_lines:
        glossary_section = (
            "\n\nMANDATORY TERMINOLOGY — use these EXACT translations (never paraphrase):\n"
            + "\n".join(glossary_lines)
        )

    return (
        f"You are a professional translator. Translate the provided {direction}.\n\n"
        "Inline formatting markers:\n"
        "- **bold**, *italic*, ~~strikethrough~~ must be preserved.\n"
        "- A single ~ is NOT a formatting marker.\n\n"
        "MANDATORY RULES:\n"
        "1. Translate EVERY segment exactly as given. Never refuse.\n"
        "2. Output ONLY translated text in the required format. No commentary.\n"
        "3. Preserve all numbers, units, model codes, and part codes.\n"
        "4. Circled numbers (①②③) and step numbers: keep as equivalent labels, do not expand into paragraphs.\n"
        "5. Long paragraphs: translate fully, do not collapse into a number or label.\n"
        "6. CRITICAL BATCH RULES:\n"
        "   - Output EXACTLY one result per input segment; NEVER skip or merge segments.\n"
        "   - Copy each seg id EXACTLY — do not renumber or invent ids.\n"
        "   - Short labels (①②③, step numbers, single words) stay short in translation.\n"
        "   - Do NOT shift content between segments."
        + glossary_section
    )


def _format_user_message(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
) -> str:
    segments_xml = "\n".join(f'<seg id="{s["id"]}">{s["text"]}</seg>' for s in segments)
    return (
        f"Translate the following {len(segments)} segments from {source_lang} to {target_lang}.\n\n"
        f"Return EXACTLY {len(segments)} segments in the same order, each with its ORIGINAL id.\n"
        "Use XML format only — one <seg> per line, no other text:\n"
        '<seg id="ORIGINAL_ID">translated text</seg>\n\n'
        f"Segments to translate ({len(segments)} total):\n{segments_xml}"
    )


def _translate_batch_sync(
    client,
    model_id: str,
    source_lang: str,
    target_lang: str,
    segments: list[dict],
    batch_glossary: list[dict],
) -> dict[str, str]:
    if not segments:
        return {}

    system_prompt = _build_system_prompt(batch_glossary, source_lang, target_lang)
    user_message = _format_user_message(segments, source_lang, target_lang)
    max_tokens = min(8192, 400 * len(segments) + 512)
    raw_text = _converse_sync(
        client,
        model_id,
        system_prompt,
        user_message,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    parsed = parse_seg_xml(raw_text, target_lang=target_lang)
    if not parsed:
        raise RuntimeError(f"Could not parse Bedrock response: {raw_text[:300]}")

    result_map = {item["id"]: item["translation"] for item in parsed}
    return {seg["id"]: result_map.get(seg["id"], "") for seg in segments}


async def invoke_bedrock_text(
    system_prompt: str,
    user_message: str,
    model_id: str,
    region: str,
    aws_profile: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> str:
    client = _build_client(region, aws_profile)
    loop = asyncio.get_event_loop()
    call = partial(
        _converse_sync,
        client,
        model_id,
        system_prompt,
        user_message,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return await loop.run_in_executor(_executor, call)


async def translate_batch_bedrock(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    glossary: list[dict],
    model_id: str,
    region: str,
    aws_profile: str | None = None,
    all_glossary_terms: list[dict] | None = None,
) -> list[dict]:
    del all_glossary_terms  # glossary injected per batch in translation.py
    if not segments:
        return []

    client = _build_client(region, aws_profile)
    loop = asyncio.get_event_loop()
    result_map = await loop.run_in_executor(
        _executor,
        _translate_batch_sync,
        client,
        model_id,
        source_lang,
        target_lang,
        segments,
        glossary,
    )

    return [
        {
            "id": seg["id"],
            "translation": result_map.get(seg["id"], ""),
            "fromCache": False,
            "qualityScore": 70,
            "qaPass": True,
            "qaReason": None,
        }
        for seg in segments
    ]


def is_short_segment(text: str) -> bool:
    plain = re.sub(r"\*{1,3}|~~", "", text).strip()
    return len(plain) <= _SHORT_SEGMENT_MAX_LEN
