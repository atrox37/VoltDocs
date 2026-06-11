from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    input_file_id TEXT,
    output_file_id TEXT,
    payload_json TEXT,
    result_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_segments (
    job_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    segment_order INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    draft_translation TEXT DEFAULT '',
    style_name TEXT,
    segment_type TEXT NOT NULL DEFAULT 'paragraph',
    status TEXT NOT NULL DEFAULT 'pending',
    qa_pass INTEGER DEFAULT 1,
    qa_reason TEXT,
    from_cache INTEGER DEFAULT 0,
    tm_quality INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, segment_id)
);

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    language TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS glossary_terms (
    id TEXT PRIMARY KEY,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    domain TEXT,
    context TEXT,
    required INTEGER NOT NULL DEFAULT 0,
    forbidden_terms_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_glossary_unique
    ON glossary_terms(source_lang, target_lang, source_term);

CREATE TABLE IF NOT EXISTS glossary_audit_logs (
    id TEXT PRIMARY KEY,
    term_id TEXT,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translation_memory (
    id TEXT PRIMARY KEY,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    quality INTEGER NOT NULL DEFAULT 100,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_lookup
    ON translation_memory(source_lang, target_lang, source_hash);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS user_roles (
    email       TEXT PRIMARY KEY NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK(role IN ('super_admin','manager','user')),
    created_at  TEXT NOT NULL,
    last_login  TEXT
);

CREATE TABLE IF NOT EXISTS role_audit_log (
    id           TEXT PRIMARY KEY,
    actor_email  TEXT NOT NULL,
    target_email TEXT NOT NULL,
    old_role     TEXT NOT NULL,
    new_role     TEXT NOT NULL,
    changed_at   TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode = WAL;")
        except sqlite3.OperationalError:
            self._conn.execute("PRAGMA journal_mode = DELETE;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        with self._lock:
            self._conn.executemany(sql, params)
            self._conn.commit()

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def query_value(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = self.query_one(sql, params)
        return None if row is None else row[0]


def json_load(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
