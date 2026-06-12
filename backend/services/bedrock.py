"""Direct AWS Bedrock translation — bypasses Lambda/API Gateway entirely.

Drop-in replacement for the Lambda HTTP call in services/translation.py.
Uses the same XML-tag segment format and retry logic as the Lambda handler.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Module-level executor so we reuse threads across calls (boto3 is sync-only)
_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="bedrock")

_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "TooManyRequestsException",
    "RequestTimeout",
    "RequestThrottled",
}

# Patterns indicating LLM refusal leaking into output — same as Lambda
_REFUSE_RE = re.compile(
    r"^(I cannot|I['\u2019]m sorry|I am sorry|As an AI|"
    r"\u5f88\u6292\u6b49|\u6211\u65e0\u6cd5|"
    r"I need the actual|I notice (you|that)|Please provide|"
    r"This (appears|seems) to be|The text .{0,30}appears to be|"
    r"Here['\u2019]s the translation with|I['\u2019]m (ready|unable)|"
    r"Note: (This|Please|If you)|---\s*\*\*Note)",
    re.IGNORECASE,
)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


def _build_client(region: str, profile: str | None) -> "boto3.client":
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client("bedrock-runtime", region_name=region)


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
            "\n\nMANDATORY TERMINOLOGY — you MUST use these exact translations whenever the source term appears. "
            "Do NOT paraphrase, substitute, or omit them:\n"
            + "\n".join(glossary_lines)
        )

    return (
        f"You are a professional translator. Translate the provided {direction}.\n\n"
        "The source text is extracted from a Word (.docx) document, spreadsheet, or Markdown file. "
        "Inline formatting is encoded with markers:\n"
        "- **double asterisks** = bold text → preserve as **text**\n"
        "- *single asterisks* = italic text → preserve as *text*\n"
        "- ~~double tildes~~ = strikethrough text → preserve as ~~text~~\n"
        "- A single ~ (tilde) is NOT a formatting marker — treat the entire segment as plain text and translate it.\n\n"
        "MANDATORY RULES — follow without exception:\n"
        "1. Translate EVERY segment exactly as given. Never refuse, question, or ask for more context.\n"
        "2. Output ONLY the translated text. No explanations, no notes, no meta-commentary.\n"
        "3. PRESERVE all **bold**, *italic*, and ~~strikethrough~~ markers exactly as they appear.\n"
        "4. Short segments (single words, labels, headings, symbols, numbers) — translate literally.\n"
        "5. Preserve all numbers, units, model codes, and part codes exactly as written.\n"
        "6. Preserve warning labels (注意/NOTE, 警告/WARNING, 危险/DANGER) in ALL CAPS.\n"
        "7. If the segment contains a single ~ before/after text (not ~~), translate the text content normally — do NOT omit it.\n"
        "8. Do NOT assume a specific industry or domain."
        + glossary_section
    )


def _call_bedrock_sync(
    client,
    model_id: str,
    system_prompt: str,
    source_lang: str,
    target_lang: str,
    segments: list[dict],
) -> list[dict]:
    """Synchronous Bedrock call with retry. Runs inside a thread-pool thread."""
    segments_xml = "\n".join(
        f'<seg id="{s["id"]}">{s["text"]}</seg>' for s in segments
    )
    user_message = (
        f"Translate the following segments from {source_lang} to {target_lang}.\n\n"
        "Output ONLY the translated segments using this exact XML format. "
        "One <seg> per line. No other text:\n"
        '<seg id="seg-1">translated text here</seg>\n'
        '<seg id="seg-2">another translated text</seg>\n\n'
        f"Segments to translate:\n{segments_xml}"
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 16384,
        # Low temperature = more deterministic, better instruction-following for translation.
        # 0.1 gives stable terminology adherence while keeping natural phrasing.
        "temperature": 0.5,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    })

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            import time
            delay = _BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "Bedrock retry %d/%d in %.1fs (error: %s)",
                attempt, _MAX_RETRIES - 1, delay, last_exc,
            )
            time.sleep(delay)
        try:
            response = client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            decoded = json.loads(response["body"].read())
            raw_text: str = (decoded.get("content") or [{}])[0].get("text", "").strip()
            if not raw_text:
                raise RuntimeError("Empty response from Bedrock")

            # Parse XML-tag format: <seg id="...">...</seg>
            results = [
                {"id": m.group(1), "translation": m.group(2).strip()}
                for m in re.finditer(r'<seg\s+id="([^"]+)">([\s\S]*?)</seg>', raw_text)
            ]
            if results:
                return results

            raise RuntimeError(f"Could not parse Bedrock response: {raw_text[:300]}")

        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in _RETRYABLE_ERROR_CODES:
                raise
            last_exc = exc
        except Exception as exc:
            last_exc = exc
            # Only retry on transient / timeout errors
            name = type(exc).__name__
            if name not in _RETRYABLE_ERROR_CODES and "Timeout" not in name and "Throttl" not in name:
                raise

    raise last_exc  # type: ignore[misc]


async def translate_batch_bedrock(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    glossary: list[dict],
    model_id: str,
    region: str,
    aws_profile: str | None = None,
) -> list[dict]:
    """Translate a batch of segments directly via Bedrock (async wrapper).

    Args:
        segments:    List of {"id": str, "text": str}
        source_lang: e.g. "zh-CN"
        target_lang: e.g. "en-US"
        glossary:    Matched glossary terms [{"source": ..., "target": ..., "context": ...}]
        model_id:    Bedrock model ID
        region:      AWS region
        aws_profile: Optional named AWS profile (None = default credential chain)

    Returns:
        List of {"id", "translation", "fromCache", "qualityScore", "qaPass", "qaReason"}
    """
    if not segments:
        return []

    system_prompt = _build_system_prompt(glossary, source_lang, target_lang)
    client = _build_client(region, aws_profile)

    loop = asyncio.get_event_loop()
    raw_results = await loop.run_in_executor(
        _executor,
        _call_bedrock_sync,
        client,
        model_id,
        system_prompt,
        source_lang,
        target_lang,
        segments,
    )

    result_map = {r["id"]: r["translation"] for r in raw_results}

    return [
        {
            "id": seg["id"],
            "translation": (
                seg["text"]  # fall back to source on refusal
                if _REFUSE_RE.match((result_map.get(seg["id"]) or "").strip())
                else (result_map.get(seg["id"]) or "")
            ),
            "fromCache": False,
            "qualityScore": 70,
            "qaPass": True,
            "qaReason": None,
        }
        for seg in segments
    ]
