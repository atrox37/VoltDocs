import fs from "node:fs";
import path from "node:path";
import { nanoid } from "nanoid";
import { getDb, nowIso } from "../db/database.js";
import { relativeToDataDir, sha256File } from "./storage.js";

export interface StoredFileRecord {
  id: string;
  owner_id: string;
  kind: string;
  original_name: string;
  storage_path: string;
  mime_type: string | null;
  size: number;
  sha256: string | null;
  created_at: string;
  expires_at: string | null;
}

export function registerFile(params: {
  ownerId: string;
  kind: string;
  originalName: string;
  filePath: string;
  mimeType?: string | null;
  expiresAt?: string | null;
}) {
  const stat = fs.statSync(params.filePath);
  const id = nanoid();
  const record: StoredFileRecord = {
    id,
    owner_id: params.ownerId,
    kind: params.kind,
    original_name: params.originalName,
    storage_path: relativeToDataDir(params.filePath),
    mime_type: params.mimeType ?? null,
    size: stat.size,
    sha256: sha256File(params.filePath),
    created_at: nowIso(),
    expires_at: params.expiresAt ?? null
  };

  getDb()
    .prepare(
      `INSERT INTO files
       (id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at, expires_at)
       VALUES (@id, @owner_id, @kind, @original_name, @storage_path, @mime_type, @size, @sha256, @created_at, @expires_at)`
    )
    .run(record);
  return record;
}

export function getFileRecord(fileId: string) {
  return getDb()
    .prepare("SELECT * FROM files WHERE id = ?")
    .get(fileId) as StoredFileRecord | undefined;
}

export function dataPathForRecord(record: StoredFileRecord, dataDir: string) {
  return path.resolve(dataDir, record.storage_path);
}

