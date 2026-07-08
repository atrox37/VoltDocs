import asyncio

from database import Database
from services.tm import (
    can_direct_use_tm,
    can_consider_weak_tm,
    classify_tm_segment,
    hash_tm_source,
    lookup_tm_segments,
    lookup_tm_candidate_segments,
    normalize_tm_source,
    prune_translation_memory,
    review_weak_tm_candidate_rule,
    should_consider_weak_reuse_tier,
    should_direct_reuse_tier,
    should_store_tm_segment,
    store_tm_segments,
    tm_quality_for_result,
    tm_quality_tier_for_result,
)
from services.translation import translate_segments


def test_normalize_tm_source_removes_markers_and_collapses_whitespace() -> None:
    assert normalize_tm_source(" **Install**   bracket \n ") == "Install bracket"


def test_classify_tm_segment_distinguishes_phase1_classes() -> None:
    assert classify_tm_segment({"source_text": "O1", "segment_type": "cell"}) == "id_or_code"
    assert classify_tm_segment({"source_text": "Level", "segment_type": "cell"}) == "short_label"
    assert classify_tm_segment({"source_text": "Overall Objective", "segment_type": "title"}) == "title_heading"
    assert classify_tm_segment({"source_text": "Please install the bracket before wiring.", "segment_type": "paragraph"}) == "sentence"
    assert classify_tm_segment(
        {
            "source_text": "Before October 31, complete the mobile demo refactor, finish routing, and finalize the reusable app architecture.",
            "segment_type": "cell",
        }
    ) == "long_paragraph"
    assert classify_tm_segment({"source_text": "Voltage EMS 2.0 版本", "segment_type": "cell"}) == "mixed_language"


def test_can_direct_use_tm_only_allows_short_labels() -> None:
    assert can_direct_use_tm({"source_text": "Level", "segment_type": "cell"}) is True
    assert can_direct_use_tm({"source_text": "Overall Objective", "segment_type": "title"}) is False
    assert can_direct_use_tm(
        {"source_text": "Before October 31, complete the mobile demo refactor.", "segment_type": "cell"}
    ) is False


def test_can_consider_weak_tm_allows_short_titles_and_medium_sentences() -> None:
    assert can_consider_weak_tm({"source_text": "Overall Objective", "segment_type": "title"}) is True
    assert can_consider_weak_tm(
        {"source_text": "Install the bracket before wiring.", "segment_type": "paragraph"}
    ) is True
    assert can_consider_weak_tm(
        {
            "source_text": "Before October 31, complete the mobile demo refactor, finish routing, and finalize the reusable app architecture.",
            "segment_type": "cell",
        }
    ) is False


def test_review_weak_tm_candidate_rule_splits_accept_reject_and_uncertain() -> None:
    accept, reason = review_weak_tm_candidate_rule(
        {"source_text": "Overall Objective", "segment_type": "title"},
        {"translation": "Overall Objective title"},
    )
    assert (accept, reason) == ("accept", None)

    reject, _ = review_weak_tm_candidate_rule(
        {"source_text": "Overall Objective", "segment_type": "title"},
        {"translation": "Overall Objective"},
    )
    assert reject == "reject"

    uncertain, reason = review_weak_tm_candidate_rule(
        {"source_text": "Install the bracket before wiring.", "segment_type": "paragraph"},
        {"translation": "Install bracket before wiring translated"},
    )
    assert uncertain == "uncertain"
    assert reason is not None


def test_tm_quality_tier_assignment_and_reuse_policies() -> None:
    assert tm_quality_tier_for_result({"human_confirmed": True}) == "human_confirmed"
    assert tm_quality_tier_for_result({"qa_pass": True, "qa_debug": {"history": [{"qaPass": True}]}}) == "qa_passed_clean"
    assert tm_quality_tier_for_result({"qa_pass": True, "qa_debug": {"history": [{"qaPass": False}, {"qaPass": True}]}}) == "repaired_or_risky"
    assert tm_quality_tier_for_result({}) == "model_generated"

    assert should_direct_reuse_tier("human_confirmed") is True
    assert should_direct_reuse_tier("qa_passed_clean") is True
    assert should_direct_reuse_tier("model_generated") is False
    assert should_consider_weak_reuse_tier("model_generated") is True
    assert should_consider_weak_reuse_tier("repaired_or_risky") is False


def test_should_store_tm_segment_filters_risky_or_low_value_content() -> None:
    clean_segment = {"source_text": "Install bracket", "segment_type": "cell"}
    clean_result = {"draft_translation": "Install the bracket", "qa_pass": True, "from_cache": False}
    assert should_store_tm_segment(clean_segment, clean_result) is True

    assert should_store_tm_segment(
        {"source_text": "12", "segment_type": "cell"},
        {"draft_translation": "12", "qa_pass": True, "from_cache": False},
    ) is False
    assert should_store_tm_segment(
        {"source_text": "Install bracket", "segment_type": "cell"},
        {"draft_translation": "", "qa_pass": True, "from_cache": False},
    ) is False
    assert should_store_tm_segment(
        {"source_text": "Install bracket", "segment_type": "cell"},
        {"draft_translation": "Install the bracket", "qa_pass": False, "from_cache": False},
    ) is False
    assert should_store_tm_segment(
        {"source_text": "Install bracket", "segment_type": "cell"},
        {"draft_translation": "Install the bracket", "qa_pass": True, "from_cache": True},
    ) is False
    assert should_store_tm_segment(
        {
            "source_text": "Before October 31, complete the mobile demo refactor, finish routing, and finalize the reusable app architecture.",
            "segment_type": "cell",
        },
        {"draft_translation": "Finish the mobile demo refactor before October 31.", "qa_pass": True, "from_cache": False},
    ) is False
    assert should_store_tm_segment(
        {"source_text": "Install bracket", "segment_type": "cell"},
        {
            "draft_translation": "Install the bracket",
            "qa_pass": True,
            "from_cache": False,
            "qa_debug": {"history": [{"qaPass": False}, {"qaPass": True}]},
        },
    ) is False


def test_store_tm_segments_tracks_insert_update_and_skip_counts(tmp_path) -> None:
    db = Database(tmp_path / "tm.db")
    segments = [
        {"id": "seg-1", "source_text": "Install bracket", "segment_type": "cell"},
        {"id": "seg-2", "source_text": "Install bracket", "segment_type": "cell"},
        {
            "id": "seg-3",
            "source_text": "Before October 31, complete the mobile demo refactor, finish routing, and finalize the reusable app architecture.",
            "segment_type": "cell",
        },
        {"id": "seg-4", "source_text": "Level", "segment_type": "cell"},
    ]
    translated = [
        {"id": "seg-1", "draft_translation": "Install the bracket", "qa_pass": True, "from_cache": False},
        {"id": "seg-2", "draft_translation": "Mount the bracket", "qa_pass": True, "from_cache": False},
        {
            "id": "seg-3",
            "draft_translation": "Complete the mobile demo refactor before October 31.",
            "qa_pass": True,
            "from_cache": False,
        },
        {"id": "seg-4", "draft_translation": "Level", "qa_pass": True, "from_cache": False},
    ]

    stats = store_tm_segments(
        db,
        segments,
        translated,
        source_lang="en-US",
        target_lang="zh-CN",
        user_id="tester@example.com",
        now="2026-07-02T00:00:00Z",
    )

    assert stats == {"inserted": 1, "updated": 1, "skipped": 2}
    stored = db.query_one("SELECT target_text FROM translation_memory")
    assert stored["target_text"] == "Mount the bracket"


def test_store_tm_segments_keeps_separate_records_for_different_segment_keys(tmp_path) -> None:
    db = Database(tmp_path / "tm_segment_keys.db")
    stats = store_tm_segments(
        db,
        [
            {"id": "seg-1", "source_text": "Overall Objective", "segment_type": "title"},
            {"id": "seg-2", "source_text": "Overall Objective", "segment_type": "cell"},
        ],
        [
            {"id": "seg-1", "draft_translation": "Overall Objective title", "qa_pass": True, "from_cache": False},
            {"id": "seg-2", "draft_translation": "Overall Objective label", "qa_pass": True, "from_cache": False},
        ],
        source_lang="en-US",
        target_lang="zh-CN",
        user_id="tester@example.com",
        now="2026-07-02T00:00:00Z",
    )

    rows = db.query_all(
        """
        SELECT segment_type, content_class, target_text, quality_tier
        FROM translation_memory
        ORDER BY segment_type, content_class, target_text
        """
    )

    assert stats == {"inserted": 2, "updated": 0, "skipped": 0}
    assert [(row["segment_type"], row["content_class"], row["target_text"], row["quality_tier"]) for row in rows] == [
        ("cell", "short_label", "Overall Objective label", "qa_passed_clean"),
        ("title", "title_heading", "Overall Objective title", "qa_passed_clean"),
    ]


def test_lookup_tm_segments_only_direct_uses_short_labels(tmp_path) -> None:
    db = Database(tmp_path / "tm_lookup.db")
    now = "2026-07-02T00:00:00Z"
    store_tm_segments(
        db,
        [{"id": "seg-1", "source_text": "Level", "segment_type": "cell"}],
        [{"id": "seg-1", "draft_translation": "Level translated", "qa_pass": True, "from_cache": False}],
        source_lang="en-US",
        target_lang="zh-CN",
        user_id="tester@example.com",
        now=now,
    )
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'global', 'en-US', 'zh-CN', ?, 'cell', 'long_paragraph', ?, ?, ?, 90, 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
        """,
        (
            "manual-long",
            hash_tm_source(normalize_tm_source("Before October 31, complete the mobile demo refactor.")),
            "Before October 31, complete the mobile demo refactor.",
            normalize_tm_source("Before October 31, complete the mobile demo refactor."),
            "Existing long paragraph translation",
            now,
            now,
        ),
    )

    hits, misses = lookup_tm_segments(
        db,
        [
            {"id": "seg-1", "source_text": "Level", "segment_type": "cell"},
            {"id": "seg-2", "source_text": "Before October 31, complete the mobile demo refactor.", "segment_type": "cell"},
        ],
        "en-US",
        "zh-CN",
    )

    assert set(hits) == {"seg-1"}
    assert hits["seg-1"]["translation"] == "Level translated"
    assert [item["id"] for item in misses] == ["seg-2"]


def test_lookup_tm_segments_requires_matching_segment_key(tmp_path) -> None:
    db = Database(tmp_path / "tm_lookup_keys.db")
    now = "2026-07-02T00:00:00Z"
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'global', 'en-US', 'zh-CN', ?, 'title', 'title_heading', ?, ?, ?, 90, 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
        """,
        (
            "title-key",
            hash_tm_source(normalize_tm_source("Overall Objective")),
            "Overall Objective",
            normalize_tm_source("Overall Objective"),
            "Title translation",
            now,
            now,
        ),
    )

    hits, misses = lookup_tm_segments(
        db,
        [{"id": "seg-1", "source_text": "Overall Objective", "segment_type": "cell"}],
        "en-US",
        "zh-CN",
    )

    assert hits == {}
    assert [item["id"] for item in misses] == ["seg-1"]


def test_lookup_tm_candidate_segments_returns_sentence_candidate(tmp_path) -> None:
    db = Database(tmp_path / "tm_weak_lookup.db")
    now = "2026-07-02T00:00:00Z"
    source = "Install the bracket before wiring."
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, quality_tier, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'filetype:docx', 'en-US', 'zh-CN', ?, 'paragraph', 'sentence', ?, ?, ?, 90, 'model_generated', 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
        """,
        (
            "sentence-candidate",
            hash_tm_source(normalize_tm_source(source)),
            source,
            normalize_tm_source(source),
            "Sentence candidate translation",
            now,
            now,
        ),
    )

    candidates, misses = lookup_tm_candidate_segments(
        db,
        [{"id": "seg-1", "source_text": source, "segment_type": "paragraph"}],
        "en-US",
        "zh-CN",
        scopes=["filetype:docx", "global"],
    )

    assert misses == []
    assert candidates["seg-1"]["translation"] == "Sentence candidate translation"
    assert candidates["seg-1"]["quality_tier"] == "model_generated"


def test_lookup_tm_segments_prefers_document_then_filetype_then_global(tmp_path) -> None:
    db = Database(tmp_path / "tm_scope_layers.db")
    now = "2026-07-02T00:00:00Z"
    source = "Level"
    source_hash = hash_tm_source(normalize_tm_source(source))
    for scope, target in (
        ("global", "Global translation"),
        ("filetype:xlsx", "Filetype translation"),
        ("document:abc123", "Document translation"),
    ):
        db.execute(
            """
            INSERT INTO translation_memory (
                id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
                target_text, quality, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
            )
            VALUES (?, ?, 'en-US', 'zh-CN', ?, 'cell', 'short_label', ?, ?, ?, 90, 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
            """,
            (scope, scope, source_hash, source, normalize_tm_source(source), target, now, now),
        )

    hits, misses = lookup_tm_segments(
        db,
        [{"id": "seg-1", "source_text": source, "segment_type": "cell"}],
        "en-US",
        "zh-CN",
        scopes=["document:abc123", "filetype:xlsx", "global"],
    )

    assert misses == []
    assert hits["seg-1"]["translation"] == "Document translation"
    assert hits["seg-1"]["scope"] == "document:abc123"


def test_store_tm_segments_writes_to_document_and_filetype_scopes(tmp_path) -> None:
    db = Database(tmp_path / "tm_write_scopes.db")
    stats = store_tm_segments(
        db,
        [{"id": "seg-1", "source_text": "Level", "segment_type": "cell"}],
        [{"id": "seg-1", "draft_translation": "Level translated", "qa_pass": True, "from_cache": False}],
        source_lang="en-US",
        target_lang="zh-CN",
        user_id="tester@example.com",
        now="2026-07-02T00:00:00Z",
        scopes=["document:docsha", "filetype:xlsx"],
    )

    scopes = [row["scope"] for row in db.query_all("SELECT scope FROM translation_memory ORDER BY scope")]

    assert stats == {"inserted": 1, "updated": 0, "skipped": 0}
    assert scopes == ["document:docsha", "filetype:xlsx"]


def test_tm_quality_for_result_prefers_cache_hits() -> None:
    assert tm_quality_for_result({"from_cache": False, "qa_pass": True}) == 90
    assert tm_quality_for_result({"from_cache": True, "tm_quality": 91, "qa_pass": True}) == 95


def test_prune_translation_memory_removes_low_value_entries_first(tmp_path) -> None:
    db = Database(tmp_path / "tm_prune.db")
    now = "2026-07-02T00:00:00Z"
    for index, quality in enumerate((70, 80, 95), start=1):
        db.execute(
            """
            INSERT INTO translation_memory (
                id, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
                target_text, quality, quality_tier, created_by, hit_count, last_hit_at, last_used_by,
                origin, locked, created_at, updated_at
            ) VALUES (?, 'en-US', 'zh-CN', ?, 'cell', 'short_label', ?, ?, ?, ?, ?, 'tester@example.com', ?, ?, NULL, 'qa_passed', ?, ?, ?)
            """,
            (
                f"id-{index}",
                f"hash-{index}",
                f"source-{index}",
                f"source-{index}",
                f"target-{index}",
                quality,
                "human_confirmed" if quality >= 95 else "model_generated",
                0 if quality < 95 else 3,
                None if quality < 95 else now,
                1 if quality >= 95 else 0,
                now,
                now,
            ),
        )

    deleted = prune_translation_memory(db, max_entries=2, prune_batch_size=1)
    remaining_ids = {row["id"] for row in db.query_all("SELECT id FROM translation_memory")}

    assert deleted == 1
    assert "id-1" not in remaining_ids
    assert remaining_ids == {"id-2", "id-3"}


def test_translate_segments_uses_tm_hit_without_calling_provider_and_does_not_rewrite_hit(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "translate_tm.db")
    store_tm_segments(
        db,
        [{"id": "seg-1", "source_text": "Level", "segment_type": "cell"}],
        [{"id": "seg-1", "draft_translation": "Level translated", "qa_pass": True, "from_cache": False}],
        source_lang="en-US",
        target_lang="zh-CN",
        user_id="tester@example.com",
        now="2026-07-02T00:00:00Z",
    )

    async def fail_translate(*args, **kwargs):
        raise AssertionError("Provider should not be called for TM hit")

    async def pass_through_qa(*, segments, drafts_by_id, **kwargs):
        return (
            {
                segment["id"]: {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                    "qa_debug": {"history": [{"qaPass": True}]},
                }
                for segment in segments
            },
            drafts_by_id,
            {"summary": {}},
        )

    monkeypatch.setattr("services.translation.translate_batch_bedrock", fail_translate)
    monkeypatch.setattr("services.translation.evaluate_segments_qa_with_repair", pass_through_qa)

    result = asyncio.run(
        translate_segments(
            segments=[{"id": "seg-1", "source_text": "Level", "segment_type": "cell"}],
            source_lang="en-US",
            target_lang="zh-CN",
            bearer_token=None,
            lambda_url="",
            timeout_seconds=30,
            db=db,
            tm_user_id="tester@example.com",
            now_iso="2026-07-02T00:00:00Z",
            tm_lookup_scopes=["global"],
            tm_write_scopes=["filetype:xlsx"],
        )
    )

    assert result["segments"][0]["from_cache"] is True
    assert result["segments"][0]["draft_translation"] == "Level translated"
    assert result["tm_stats"]["hits"] == 1
    assert result["tm_stats"]["stored"] == 0
    assert result["tm_stats"]["inserted"] == 0
    assert result["tm_stats"]["updated"] == 0
    assert result["tm_stats"]["skipped"] == 1
    hit_count = db.query_value("SELECT hit_count FROM translation_memory")
    assert hit_count == 1


def test_translate_segments_reports_tm_stats_for_new_clean_entry(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "tm_stats.db")

    async def fake_translate(*args, **kwargs):
        return [{"id": "seg-1", "translation": "Install the bracket", "fromCache": False, "qualityScore": 90}]

    async def pass_through_qa(*, segments, drafts_by_id, **kwargs):
        return (
            {
                segment["id"]: {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                    "qa_debug": {"history": [{"qaPass": True}]},
                }
                for segment in segments
            },
            drafts_by_id,
            {"summary": {}},
        )

    monkeypatch.setattr("services.translation._translate_chunk_via_bedrock", fake_translate)
    monkeypatch.setattr("services.translation.evaluate_segments_qa_with_repair", pass_through_qa)

    stats: dict[str, int] = {}
    result = asyncio.run(
        translate_segments(
            segments=[{"id": "seg-1", "source_text": "Install bracket", "segment_type": "cell"}],
            source_lang="en-US",
            target_lang="zh-CN",
            bearer_token=None,
            lambda_url="",
            timeout_seconds=30,
            db=db,
            tm_user_id="tester@example.com",
            now_iso="2026-07-02T00:00:00Z",
            tm_lookup_scopes=["filetype:xlsx", "global"],
            tm_write_scopes=["document:docsha", "filetype:xlsx"],
            tm_stats=stats,
        )
    )

    assert result["tm_stats"]["hits"] == 0
    assert result["tm_stats"]["stored"] == 1
    assert result["tm_stats"]["inserted"] == 1
    assert result["tm_stats"]["updated"] == 0
    assert result["tm_stats"]["skipped"] == 0
    assert stats["inserted"] == 1
    assert stats["stored"] == 1


def test_translate_segments_accepts_ai_approved_weak_tm_candidate_without_provider(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "tm_weak_accept.db")
    source = "Install the bracket before wiring."
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, quality_tier, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'filetype:docx', 'en-US', 'zh-CN', ?, 'paragraph', 'sentence', ?, ?, ?, 90, 'qa_passed_clean', 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
        """,
        (
            "weak-candidate",
            hash_tm_source(normalize_tm_source(source)),
            source,
            normalize_tm_source(source),
            "Approved weak candidate",
            "2026-07-02T00:00:00Z",
            "2026-07-02T00:00:00Z",
        ),
    )

    async def fail_translate(*args, **kwargs):
        raise AssertionError("Provider should not be called for accepted weak TM candidate")

    async def pass_through_qa(*, segments, drafts_by_id, **kwargs):
        return (
            {
                segment["id"]: {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                    "qa_debug": {"history": [{"qaPass": True}]},
                }
                for segment in segments
            },
            drafts_by_id,
            {"summary": {}},
        )

    class Verdict:
        def __init__(self, pass_, confidence):
            self.pass_ = pass_
            self.confidence = confidence
            self.reason = None

    async def approve_tm_candidates(*args, **kwargs):
        return {"seg-1": Verdict(True, 0.95)}

    monkeypatch.setattr("services.translation._translate_chunk_via_bedrock", fail_translate)
    monkeypatch.setattr("services.translation.evaluate_segments_qa_with_repair", pass_through_qa)
    monkeypatch.setattr("services.translation.adjudicate_tm_candidates", approve_tm_candidates)

    result = asyncio.run(
        translate_segments(
            segments=[{"id": "seg-1", "source_text": source, "segment_type": "paragraph"}],
            source_lang="en-US",
            target_lang="zh-CN",
            bearer_token=None,
            lambda_url="",
            timeout_seconds=30,
            db=db,
            tm_user_id="tester@example.com",
            now_iso="2026-07-02T00:00:00Z",
            tm_lookup_scopes=["filetype:docx", "global"],
            tm_write_scopes=["document:docsha", "filetype:docx"],
            tm_weak_ai_enabled=True,
        )
    )

    assert result["segments"][0]["from_cache"] is True
    assert result["segments"][0]["draft_translation"] == "Approved weak candidate"
    assert result["tm_stats"]["hits"] == 1


def test_translate_segments_rejects_weak_tm_candidate_and_falls_back_to_provider(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "tm_weak_reject.db")
    source = "Install the bracket before wiring."
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, quality_tier, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'filetype:docx', 'en-US', 'zh-CN', ?, 'paragraph', 'sentence', ?, ?, ?, 90, 'qa_passed_clean', 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
        """,
        (
            "weak-candidate",
            hash_tm_source(normalize_tm_source(source)),
            source,
            normalize_tm_source(source),
            "Rejected weak candidate",
            "2026-07-02T00:00:00Z",
            "2026-07-02T00:00:00Z",
        ),
    )

    async def fake_translate(*args, **kwargs):
        return [{"id": "seg-1", "translation": "Provider translation", "fromCache": False, "qualityScore": 90}]

    async def pass_through_qa(*, segments, drafts_by_id, **kwargs):
        return (
            {
                segment["id"]: {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                    "qa_debug": {"history": [{"qaPass": True}]},
                }
                for segment in segments
            },
            drafts_by_id,
            {"summary": {}},
        )

    class Verdict:
        def __init__(self, pass_, confidence):
            self.pass_ = pass_
            self.confidence = confidence
            self.reason = "不适合当前上下文"

    async def reject_tm_candidates(*args, **kwargs):
        return {"seg-1": Verdict(False, 0.95)}

    monkeypatch.setattr("services.translation._translate_chunk_via_bedrock", fake_translate)
    monkeypatch.setattr("services.translation.evaluate_segments_qa_with_repair", pass_through_qa)
    monkeypatch.setattr("services.translation.adjudicate_tm_candidates", reject_tm_candidates)

    result = asyncio.run(
        translate_segments(
            segments=[{"id": "seg-1", "source_text": source, "segment_type": "paragraph"}],
            source_lang="en-US",
            target_lang="zh-CN",
            bearer_token=None,
            lambda_url="",
            timeout_seconds=30,
            db=db,
            tm_user_id="tester@example.com",
            now_iso="2026-07-02T00:00:00Z",
            tm_lookup_scopes=["filetype:docx", "global"],
            tm_write_scopes=["document:docsha", "filetype:docx"],
            tm_weak_ai_enabled=True,
        )
    )

    assert result["segments"][0]["from_cache"] is False
    assert result["segments"][0]["draft_translation"] == "Provider translation"
    assert result["tm_stats"]["hits"] == 0


def test_translate_segments_skips_weak_tm_ai_when_disabled(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "tm_weak_disabled.db")
    source = "Install the bracket before wiring."
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, quality_tier, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'filetype:docx', 'en-US', 'zh-CN', ?, 'paragraph', 'sentence', ?, ?, ?, 90, 'qa_passed_clean', 'tester@example.com', 0, NULL, NULL, 'qa_passed', 0, ?, ?)
        """,
        (
            "weak-candidate",
            hash_tm_source(normalize_tm_source(source)),
            source,
            normalize_tm_source(source),
            "Disabled weak candidate",
            "2026-07-02T00:00:00Z",
            "2026-07-02T00:00:00Z",
        ),
    )

    async def fake_translate(*args, **kwargs):
        return [{"id": "seg-1", "translation": "Provider translation", "fromCache": False, "qualityScore": 90}]

    async def pass_through_qa(*, segments, drafts_by_id, **kwargs):
        return (
            {
                segment["id"]: {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                    "qa_debug": {"history": [{"qaPass": True}]},
                }
                for segment in segments
            },
            drafts_by_id,
            {"summary": {}},
        )

    async def reject_tm_candidates(*args, **kwargs):
        raise AssertionError("Weak TM candidates should not be sent to AI review when disabled")

    monkeypatch.setattr("services.translation._translate_chunk_via_bedrock", fake_translate)
    monkeypatch.setattr("services.translation.evaluate_segments_qa_with_repair", pass_through_qa)
    monkeypatch.setattr("services.translation.adjudicate_tm_candidates", reject_tm_candidates)

    result = asyncio.run(
        translate_segments(
            segments=[{"id": "seg-1", "source_text": source, "segment_type": "paragraph"}],
            source_lang="en-US",
            target_lang="zh-CN",
            bearer_token=None,
            lambda_url="",
            timeout_seconds=30,
            db=db,
            tm_user_id="tester@example.com",
            now_iso="2026-07-02T00:00:00Z",
            tm_lookup_scopes=["filetype:docx", "global"],
            tm_write_scopes=["document:docsha", "filetype:docx"],
        )
    )

    assert result["segments"][0]["from_cache"] is False
    assert result["segments"][0]["draft_translation"] == "Provider translation"


def test_translate_segments_dedupes_repeated_xlsx_text_before_translation(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "xlsx_dedupe.db")
    captured: dict[str, object] = {"chunks": []}

    async def fake_translate(chunk, **kwargs):
        captured["chunks"].append([segment["id"] for segment in chunk])
        return [
            {
                "id": segment["id"],
                "translation": f"{segment['id']}-translated",
                "fromCache": False,
                "qualityScore": 100,
            }
            for segment in chunk
        ]

    async def pass_through_qa(*, segments, drafts_by_id, **kwargs):
        return (
            {
                segment["id"]: {
                    "qa_pass": True,
                    "qa_reason": None,
                    "qa_rule_name": None,
                    "qa_failure_type": None,
                    "qa_debug": {"history": [{"qaPass": True}]},
                }
                for segment in segments
            },
            drafts_by_id,
            {"summary": {}},
        )

    monkeypatch.setattr("services.translation._translate_chunk_via_bedrock", fake_translate)
    monkeypatch.setattr("services.translation.evaluate_segments_qa_with_repair", pass_through_qa)

    result = asyncio.run(
        translate_segments(
            segments=[
                {"id": "seg-1", "source_text": "Level", "plain_text": "Level", "segment_type": "cell", "style_name": "Sheet A"},
                {"id": "seg-2", "source_text": "Level", "plain_text": "Level", "segment_type": "cell", "style_name": "Sheet A"},
                {"id": "seg-3", "source_text": "Torque", "plain_text": "Torque", "segment_type": "cell", "style_name": "Sheet A"},
            ],
            source_lang="en-US",
            target_lang="zh-CN",
            file_type="xlsx",
            bearer_token=None,
            lambda_url="",
            timeout_seconds=30,
            db=db,
            tm_user_id="tester@example.com",
            now_iso="2026-07-02T00:00:00Z",
            tm_lookup_scopes=["filetype:xlsx", "global"],
            tm_write_scopes=["filetype:xlsx"],
        )
    )

    translated_ids = [segment_id for chunk in captured["chunks"] for segment_id in chunk]
    assert set(translated_ids) == {"seg-1", "seg-3"}
    assert "seg-2" not in translated_ids
    assert [segment["id"] for segment in result["segments"]] == ["seg-1", "seg-2", "seg-3"]
    assert result["segments"][0]["draft_translation"] == "seg-1-translated"
    assert result["segments"][1]["draft_translation"] == "seg-1-translated"
    assert result["segments"][2]["draft_translation"] == "seg-3-translated"
    assert result["segments"][1]["qa_pass"] is True


def test_store_tm_segments_does_not_downgrade_human_confirmed_tier(tmp_path) -> None:
    db = Database(tmp_path / "tm_human_tier.db")
    now = "2026-07-02T00:00:00Z"
    source = "Level"
    db.execute(
        """
        INSERT INTO translation_memory (
            id, scope, source_lang, target_lang, source_hash, segment_type, content_class, source_text, source_text_normalized,
            target_text, quality, quality_tier, created_by, hit_count, last_hit_at, last_used_by, origin, locked, created_at, updated_at
        )
        VALUES (?, 'filetype:xlsx', 'en-US', 'zh-CN', ?, 'cell', 'short_label', ?, ?, ?, 99, 'human_confirmed', 'tester@example.com', 0, NULL, NULL, 'human_confirmed', 0, ?, ?)
        """,
        (
            "human-row",
            hash_tm_source(normalize_tm_source(source)),
            source,
            normalize_tm_source(source),
            "Approved human translation",
            now,
            now,
        ),
    )

    stats = store_tm_segments(
        db,
        [{"id": "seg-1", "source_text": source, "segment_type": "cell"}],
        [{"id": "seg-1", "draft_translation": "Machine candidate", "qa_pass": True, "from_cache": False}],
        source_lang="en-US",
        target_lang="zh-CN",
        user_id="tester@example.com",
        now=now,
        scopes=["filetype:xlsx"],
    )

    row = db.query_one("SELECT target_text, quality_tier FROM translation_memory WHERE id = 'human-row'")
    assert stats == {"inserted": 0, "updated": 1, "skipped": 0}
    assert row["target_text"] == "Approved human translation"
    assert row["quality_tier"] == "human_confirmed"
