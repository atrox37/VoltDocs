import fs from "node:fs";
import Database from "better-sqlite3";
import { config, paths } from "../config.js";

let db: Database.Database;

export function getDb() {
  if (!db) {
    fs.mkdirSync(paths.db, { recursive: true });
    db = new Database(config.databasePath);
    db.pragma("journal_mode = WAL");
    db.pragma("foreign_keys = ON");
    migrate(db);
  }
  return db;
}

function migrate(database: Database.Database) {
  database.exec(`
    CREATE TABLE IF NOT EXISTS files (
      id TEXT PRIMARY KEY,
      owner_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      original_name TEXT NOT NULL,
      storage_path TEXT NOT NULL,
      mime_type TEXT,
      size INTEGER NOT NULL,
      sha256 TEXT,
      created_at TEXT NOT NULL,
      expires_at TEXT
    );

    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      type TEXT NOT NULL,
      status TEXT NOT NULL,
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

    CREATE TABLE IF NOT EXISTS review_records (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      source_file_id TEXT,
      translated_file_id TEXT,
      file_name TEXT NOT NULL,
      source_lang TEXT NOT NULL,
      target_lang TEXT NOT NULL,
      status TEXT NOT NULL,
      segments_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  `);
}

export function nowIso() {
  return new Date().toISOString();
}

