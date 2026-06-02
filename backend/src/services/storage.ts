import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { nanoid } from "nanoid";
import { paths } from "../config.js";

export function ensureRuntimeDirs() {
  for (const dir of Object.values(paths)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function sanitizeFileName(name: string) {
  const base = path.basename(name || "file");
  const cleaned = base.replace(/[^\p{L}\p{N}._ -]+/gu, "-").trim();
  return cleaned || "file";
}

export function createStoredFileName(originalName: string) {
  const safe = sanitizeFileName(originalName);
  return `${nanoid(12)}-${safe}`;
}

export function sha256File(filePath: string) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

export function resolveStoragePath(relativePath: string) {
  const full = path.resolve(paths.uploads, "..", relativePath);
  const root = path.resolve(paths.uploads, "..");
  if (!full.startsWith(root)) {
    throw new Error("Invalid storage path");
  }
  return full;
}

export function relativeToDataDir(filePath: string) {
  const dataRoot = path.resolve(paths.uploads, "..");
  const relative = path.relative(dataRoot, filePath);
  if (relative.startsWith("..")) {
    throw new Error("File is outside data directory");
  }
  return relative;
}

