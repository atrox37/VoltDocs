import sqlite3

from database import APP_TABLES, Database, INITIAL_SCHEMA_SQL


def test_database_applies_initial_migration_for_new_db(tmp_path) -> None:
    db_path = tmp_path / "voltdocs.db"

    db = Database(db_path)

    migration_names = [row["name"] for row in db.query_all("SELECT name FROM schema_migrations ORDER BY name")]
    table_names = {
        row["name"]
        for row in db.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert migration_names == [
        "001_initial_schema",
        "002_translation_memory_metadata",
        "003_translation_memory_scope_index",
        "004_job_segment_glossary_debug",
        "005_job_segment_qa_debug",
        "006_translation_memory_segment_keys",
        "007_translation_memory_quality_tier",
    ]
    assert APP_TABLES.issubset(table_names)


def test_database_stamps_existing_legacy_schema_without_reapplying(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(INITIAL_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO user_roles (email, role, created_at) VALUES (?, ?, ?)",
        ("legacy@example.com", "user", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    db = Database(db_path)

    migration_names = [row["name"] for row in db.query_all("SELECT name FROM schema_migrations ORDER BY name")]
    user_count = db.query_value("SELECT COUNT(*) FROM user_roles WHERE email = ?", ("legacy@example.com",))

    assert migration_names == [
        "001_initial_schema",
        "002_translation_memory_metadata",
        "003_translation_memory_scope_index",
        "004_job_segment_glossary_debug",
        "005_job_segment_qa_debug",
        "006_translation_memory_segment_keys",
        "007_translation_memory_quality_tier",
    ]
    assert user_count == 1


def test_database_applies_missing_tables_to_partial_legacy_schema(tmp_path) -> None:
    db_path = tmp_path / "partial.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE files (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            original_name TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            mime_type TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path)

    migration_names = [row["name"] for row in db.query_all("SELECT name FROM schema_migrations ORDER BY name")]
    jobs_table = db.query_one(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    )

    assert migration_names == [
        "001_initial_schema",
        "002_translation_memory_metadata",
        "003_translation_memory_scope_index",
        "004_job_segment_glossary_debug",
        "005_job_segment_qa_debug",
        "006_translation_memory_segment_keys",
        "007_translation_memory_quality_tier",
    ]
    assert jobs_table is not None


def test_database_adds_glossary_debug_column_for_job_segments(tmp_path) -> None:
    db_path = tmp_path / "columns.db"

    db = Database(db_path)

    columns = {
        row["name"]
        for row in db.query_all("PRAGMA table_info(job_segments)")
    }

    assert "glossary_debug_json" in columns
    assert "qa_debug_json" in columns


def test_database_adds_translation_memory_segment_key_columns(tmp_path) -> None:
    db_path = tmp_path / "tm_columns.db"

    db = Database(db_path)

    columns = {
        row["name"]
        for row in db.query_all("PRAGMA table_info(translation_memory)")
    }

    assert "segment_type" in columns
    assert "content_class" in columns
    assert "quality_tier" in columns
