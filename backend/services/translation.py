from __future__ import annotations

import asyncio
import logging
from typing import Callable

import httpx

from services.bedrock import translate_batch_bedrock
from services.docx.markup import clean_translation_artifacts, normalize_marker_spacing, preserve_circled_prefix
from services.glossary_matcher import select_terms_for_texts
from services.qa_hybrid import evaluate_segments_qa_with_repair
from services.prompt import build_system_prompt

logger = logging.getLogger(__name__)

# Statuses that are safe to retry (transient server/gateway errors)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0   # seconds; actual delay = base * 2^attempt
_MAX_CONCURRENCY = 5       # max simultaneous Lambda requests


def _finalize_draft(source: str, translation: str, target_lang: str = "") -> str:
    text = preserve_circled_prefix(source, translation or "")
    text = normalize_marker_spacing(text)
    return clean_translation_artifacts(text, target_lang=target_lang)


def _split_into_batches(
    segments: list[dict],
    max_bytes: int,
    max_segments: int,
) -> list[list[dict]]:
    """Split segments into byte/count-limited batches for Bedrock."""
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_bytes: int = 0

    for segment in segments:
        text = segment["source_text"]
        segment_bytes = len(text.encode("utf-8"))

        if segment_bytes > max_bytes:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_bytes = 0
            batches.append([segment])
            continue

        if current_batch and (
            current_bytes + segment_bytes > max_bytes
            or len(current_batch) >= max_segments
        ):
            batches.append(current_batch)
            current_batch = []
            current_bytes = 0

        current_batch.append(segment)
        current_bytes += segment_bytes

    if current_batch:
        batches.append(current_batch)
    return batches


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    headers: dict,
    semaphore: asyncio.Semaphore,
) -> httpx.Response:
    """POST with exponential-backoff retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        async with semaphore:
            try:
                response = await client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Translation request network error (attempt %d/%d): %s - retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
                continue

        if response.status_code not in _RETRYABLE_STATUSES:
            return response

        last_exc = httpx.HTTPStatusError(
            f"{response.status_code} from Lambda",
            request=response.request,
            response=response,
        )
        delay = _RETRY_BASE_DELAY * (2 ** attempt)
        logger.warning(
            "Translation request got %d (attempt %d/%d) - retrying in %.1fs",
            response.status_code, attempt + 1, _MAX_RETRIES, delay,
        )
        await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


async def _translate_chunk_via_lambda(
    chunk: list[dict],
    source_lang: str,
    target_lang: str,
    bearer_token: str | None,
    lambda_url: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    glossary_terms: list[dict] | None,
    glossary_max_terms: int,
    glossary_max_prompt_chars: int,
) -> list[dict]:
    matched_glossary: list[dict] = []
    system_prompt: str | None = None
    if glossary_terms:
        matched_glossary = select_terms_for_texts(
            glossary_terms,
            [item["source_text"] for item in chunk],
            glossary_max_terms,
            glossary_max_prompt_chars,
        )
        if matched_glossary:
            system_prompt = build_system_prompt(matched_glossary, source_lang, target_lang)

    payload: dict[str, object] = {
        "sourceLang": source_lang,
        "targetLang": target_lang,
        "segments": [{"id": item["id"], "text": item["source_text"]} for item in chunk],
    }
    if system_prompt:
        payload["systemPrompt"] = system_prompt
    if matched_glossary:
        payload["glossary"] = matched_glossary

    headers: dict[str, str] = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    response = await _post_with_retry(
        client,
        f"{lambda_url.rstrip('/')}/translate/batch",
        payload,
        headers,
        semaphore,
    )
    response.raise_for_status()
    return response.json().get("segments", [])


async def _translate_chunk_via_bedrock(
    chunk: list[dict],
    source_lang: str,
    target_lang: str,
    glossary_terms: list[dict] | None,
    glossary_max_terms: int,
    glossary_max_prompt_chars: int,
    model_id: str,
    region: str,
    aws_profile: str | None,
) -> list[dict]:
    matched_glossary: list[dict] = []
    if glossary_terms:
        matched_glossary = select_terms_for_texts(
            glossary_terms,
            [item["source_text"] for item in chunk],
            glossary_max_terms,
            glossary_max_prompt_chars,
        )

    segments_input = [{"id": item["id"], "text": item["source_text"]} for item in chunk]
    return await translate_batch_bedrock(
        segments=segments_input,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary=matched_glossary,
        model_id=model_id,
        region=region,
        aws_profile=aws_profile or None,
        all_glossary_terms=glossary_terms,
    )


async def translate_segments(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    bearer_token: str | None,
    lambda_url: str,
    timeout_seconds: int,
    glossary_terms: list[dict] | None = None,
    glossary_max_terms: int = 100,
    glossary_max_prompt_chars: int = 12000,
    batch_max_bytes: int = 5000,
    batch_max_segments: int = 120,
    bedrock_model_id: str = "us.amazon.nova-lite-v1:0",
    bedrock_region: str = "us-east-1",
    bedrock_aws_profile: str = "",
    qa_ai_enabled: bool = True,
    qa_ai_model_id: str = "us.amazon.nova-micro-v1:0",
    qa_ai_uncertain_threshold: float = 0.75,
    qa_ai_batch_max_segments: int = 40,
    qa_repair_enabled: bool = True,
    qa_repair_max_attempts: int = 2,
    qa_repair_batch_max_segments: int = 40,
    on_batch_done: "Callable[[int, int], None] | None" = None,
) -> list[dict]:
    use_bedrock = not lambda_url.strip()

    if use_bedrock:
        logger.info("Translation mode: Bedrock direct (model=%s region=%s)", bedrock_model_id, bedrock_region)
    else:
        logger.info("Translation mode: Lambda (%s)", lambda_url)

    batches = _split_into_batches(segments, batch_max_bytes, batch_max_segments)

    # -- Bedrock direct mode --
    if use_bedrock:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        total_batches = len(batches)
        completed = 0
        completed_lock = asyncio.Lock()

        async def _bounded_bedrock(chunk: list[dict]) -> list[dict]:
            nonlocal completed
            async with semaphore:
                result = await _translate_chunk_via_bedrock(
                    chunk=chunk,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    glossary_terms=glossary_terms,
                    glossary_max_terms=glossary_max_terms,
                    glossary_max_prompt_chars=glossary_max_prompt_chars,
                    model_id=bedrock_model_id,
                    region=bedrock_region,
                    aws_profile=bedrock_aws_profile or None,
                )
            async with completed_lock:
                completed += 1
                if on_batch_done:
                    on_batch_done(completed, total_batches)
            return result

        batch_results: list[list[dict]] = await asyncio.gather(
            *[_bounded_bedrock(chunk) for chunk in batches]
        )

        results_by_id: dict[str, dict] = {}
        for batch in batch_results:
            for item in batch:
                results_by_id[item["id"]] = item

        drafts_by_id = {
            segment["id"]: _finalize_draft(
                segment["source_text"],
                results_by_id.get(segment["id"], {}).get("translation", ""),
                target_lang,
            )
            for segment in segments
        }
        qa_results, drafts_by_id = await evaluate_segments_qa_with_repair(
            segments=segments,
            drafts_by_id=drafts_by_id,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
            qa_ai_enabled=qa_ai_enabled,
            bedrock_model_id=qa_ai_model_id or bedrock_model_id,
            bedrock_region=bedrock_region,
            bedrock_aws_profile=bedrock_aws_profile,
            qa_ai_uncertain_threshold=qa_ai_uncertain_threshold,
            qa_ai_batch_max_segments=qa_ai_batch_max_segments,
            qa_repair_enabled=qa_repair_enabled,
            qa_repair_max_attempts=qa_repair_max_attempts,
            qa_repair_batch_max_segments=qa_repair_batch_max_segments,
            qa_repair_model_id=bedrock_model_id,
            glossary_max_terms=glossary_max_terms,
            glossary_max_prompt_chars=glossary_max_prompt_chars,
        )

        translated: list[dict] = []
        for segment in segments:
            raw = results_by_id.get(segment["id"], {})
            qa = qa_results.get(segment["id"], {"qa_pass": True, "qa_reason": None})
            translated.append({
                "id": segment["id"],
                "draft_translation": drafts_by_id.get(segment["id"], ""),
                "from_cache": bool(raw.get("fromCache", False)),
                "tm_quality": int(raw.get("qualityScore", 0)),
                "qa_pass": qa["qa_pass"],
                "qa_reason": qa["qa_reason"],
            })
        return translated

    # -- Lambda mode --
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    total_batches = len(batches)
    completed = 0
    completed_lock = asyncio.Lock()

    async def _bounded_lambda(chunk: list[dict]) -> list[dict]:
        nonlocal completed
        result = await _translate_chunk_via_lambda(
            chunk=chunk,
            source_lang=source_lang,
            target_lang=target_lang,
            bearer_token=bearer_token,
            lambda_url=lambda_url,
            client=client,
            semaphore=semaphore,
            glossary_terms=glossary_terms,
            glossary_max_terms=glossary_max_terms,
            glossary_max_prompt_chars=glossary_max_prompt_chars,
        )
        async with completed_lock:
            completed += 1
            if on_batch_done:
                on_batch_done(completed, total_batches)
        return result

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        batch_results = await asyncio.gather(*[_bounded_lambda(chunk) for chunk in batches])

    results_by_id = {}
    for batch in batch_results:
        for item in batch:
            results_by_id[item["id"]] = item

    drafts_by_id = {
        segment["id"]: _finalize_draft(
            segment["source_text"],
            results_by_id.get(segment["id"], {}).get("translation", ""),
            target_lang,
        )
        for segment in segments
    }
    qa_results, drafts_by_id = await evaluate_segments_qa_with_repair(
        segments=segments,
        drafts_by_id=drafts_by_id,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_terms=glossary_terms,
        qa_ai_enabled=qa_ai_enabled,
        bedrock_model_id=qa_ai_model_id or bedrock_model_id,
        bedrock_region=bedrock_region,
        bedrock_aws_profile=bedrock_aws_profile,
        qa_ai_uncertain_threshold=qa_ai_uncertain_threshold,
        qa_ai_batch_max_segments=qa_ai_batch_max_segments,
        qa_repair_enabled=qa_repair_enabled,
        qa_repair_max_attempts=qa_repair_max_attempts,
        qa_repair_batch_max_segments=qa_repair_batch_max_segments,
        qa_repair_model_id=bedrock_model_id,
        glossary_max_terms=glossary_max_terms,
        glossary_max_prompt_chars=glossary_max_prompt_chars,
    )

    translated = []
    for segment in segments:
        raw = results_by_id.get(segment["id"], {})
        qa = qa_results.get(segment["id"], {"qa_pass": True, "qa_reason": None})
        translated.append({
            "id": segment["id"],
            "draft_translation": drafts_by_id.get(segment["id"], ""),
            "from_cache": bool(raw.get("fromCache", False)),
            "tm_quality": int(raw.get("qualityScore", 0)),
            "qa_pass": qa["qa_pass"],
            "qa_reason": qa["qa_reason"],
        })
    return translated
