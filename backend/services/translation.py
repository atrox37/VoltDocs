from __future__ import annotations

import asyncio
import logging
from typing import Callable

import httpx

from services.bedrock import translate_batch_bedrock
from services.glossary_matcher import select_terms_for_texts
from services.qa import run_all_checks
from services.prompt import build_system_prompt

logger = logging.getLogger(__name__)

# Statuses that are safe to retry (transient server/gateway errors)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0   # seconds; actual delay = base * 2^attempt
_MAX_CONCURRENCY = 5       # max simultaneous Lambda requests


def _split_into_batches(
    segments: list[dict],
    max_bytes: int,
    max_segments: int,
) -> list[list[dict]]:
    """Split segments into batches bounded by byte size and segment count.

    Rules:
    - A batch is sealed when adding the next segment would exceed max_bytes OR
      the batch already has max_segments entries.
    - A single segment that exceeds max_bytes on its own is placed alone in a
      batch (at-least-one guarantee -- never blocks progress).
    """
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_bytes: int = 0

    for segment in segments:
        segment_bytes = len(segment["source_text"].encode("utf-8"))

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
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    bedrock_region: str = "us-east-1",
    bedrock_aws_profile: str = "",
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

        translated: list[dict] = []
        for segment in segments:
            raw = results_by_id.get(segment["id"], {})
            draft = raw.get("translation", "")
            qa_reason = run_all_checks(
                source=segment["source_text"],
                translation=draft,
                source_lang=source_lang,
                target_lang=target_lang,
                glossary_terms=glossary_terms,
            )
            translated.append({
                "id": segment["id"],
                "draft_translation": draft,
                "from_cache": bool(raw.get("fromCache", False)),
                "tm_quality": int(raw.get("qualityScore", 0)),
                "qa_pass": qa_reason is None,
                "qa_reason": qa_reason,
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

    translated = []
    for segment in segments:
        raw = results_by_id.get(segment["id"], {})
        draft = raw.get("translation", "")
        qa_reason = run_all_checks(
            source=segment["source_text"],
            translation=draft,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_terms=glossary_terms,
        )
        translated.append({
            "id": segment["id"],
            "draft_translation": draft,
            "from_cache": bool(raw.get("fromCache", False)),
            "tm_quality": int(raw.get("qualityScore", 0)),
            "qa_pass": qa_reason is None,
            "qa_reason": qa_reason,
        })
    return translated
