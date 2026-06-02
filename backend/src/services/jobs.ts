import fs from "node:fs";
import path from "node:path";
import { nanoid } from "nanoid";
import { getDb, nowIso } from "../db/database.js";
import { paths } from "../config.js";
import { runPandoc } from "./pandoc.js";
import { registerFile } from "./fileRegistry.js";
import { extractDocxSegments, translateSegments } from "./translation.js";

type JobType = "convert" | "translation";

interface CreateJobInput {
  userId: string;
  type: JobType;
  inputFileId: string;
  payload: Record<string, unknown>;
}

interface JobRow {
  id: string;
  user_id: string;
  type: JobType;
  status: string;
  progress: number;
  input_file_id: string;
  output_file_id: string | null;
  payload_json: string | null;
  result_json: string | null;
  error_message: string | null;
}

let running = false;

export function createJob(input: CreateJobInput) {
  const id = nanoid();
  getDb()
    .prepare(
      `INSERT INTO jobs
       (id, user_id, type, status, progress, input_file_id, payload_json, created_at)
       VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)`
    )
    .run(id, input.userId, input.type, input.inputFileId, JSON.stringify(input.payload), nowIso());
  queueMicrotask(() => void runWorker());
  return getJob(id);
}

export function getJob(id: string) {
  return getDb().prepare("SELECT * FROM jobs WHERE id = ?").get(id) as JobRow | undefined;
}

export function listJobs(userId: string) {
  return getDb()
    .prepare("SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 50")
    .all(userId) as JobRow[];
}

function updateJob(id: string, patch: Record<string, unknown>) {
  const keys = Object.keys(patch);
  if (keys.length === 0) return;
  const assignments = keys.map((key) => `${key} = @${key}`).join(", ");
  getDb().prepare(`UPDATE jobs SET ${assignments} WHERE id = @id`).run({ id, ...patch });
}

async function runWorker() {
  if (running) return;
  running = true;
  try {
    while (true) {
      const job = getDb()
        .prepare("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1")
        .get() as JobRow | undefined;
      if (!job) return;
      updateJob(job.id, { status: "running", started_at: nowIso(), progress: 5 });
      try {
        if (job.type === "convert") await runConvertJob(job);
        if (job.type === "translation") await runTranslationJob(job);
      } catch (error) {
        updateJob(job.id, {
          status: "failed",
          error_message: error instanceof Error ? error.message : String(error),
          finished_at: nowIso()
        });
      }
    }
  } finally {
    running = false;
  }
}

async function runConvertJob(job: JobRow) {
  const input = getDb().prepare("SELECT * FROM files WHERE id = ?").get(job.input_file_id) as { storage_path: string; original_name: string };
  const payload = JSON.parse(job.payload_json ?? "{}") as { outputFormat?: string };
  const outputFormat = payload.outputFormat === "md" ? "md" : "docx";
  const inputPath = path.join(paths.uploads, "..", input.storage_path);
  const workDir = path.join(paths.jobs, job.id);
  const outputName = `${path.parse(input.original_name).name}.${outputFormat}`;
  const outputPath = path.join(paths.outputs, `${job.id}-${outputName}`);
  fs.mkdirSync(workDir, { recursive: true });
  updateJob(job.id, { progress: 20 });
  await runPandoc([inputPath, "-o", outputPath], workDir);
  const file = registerFile({
    ownerId: job.user_id,
    kind: "convert-output",
    originalName: outputName,
    filePath: outputPath,
    mimeType: outputFormat === "docx" ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "text/markdown"
  });
  updateJob(job.id, {
    status: "succeeded",
    progress: 100,
    output_file_id: file.id,
    result_json: JSON.stringify({ fileId: file.id, fileName: outputName }),
    finished_at: nowIso()
  });
}

async function runTranslationJob(job: JobRow) {
  const input = getDb().prepare("SELECT * FROM files WHERE id = ?").get(job.input_file_id) as { storage_path: string; original_name: string };
  const payload = JSON.parse(job.payload_json ?? "{}") as { sourceLang: string; targetLang: string; bearerToken?: string };
  const inputPath = path.join(paths.uploads, "..", input.storage_path);
  updateJob(job.id, { progress: 15 });
  const segments = await extractDocxSegments(inputPath);
  updateJob(job.id, { progress: 35 });
  const translated = await translateSegments({
    sourceLang: payload.sourceLang,
    targetLang: payload.targetLang,
    segments,
    bearerToken: payload.bearerToken
  });
  updateJob(job.id, {
    status: "succeeded",
    progress: 100,
    result_json: JSON.stringify({
      fileName: input.original_name,
      sourceLang: payload.sourceLang,
      targetLang: payload.targetLang,
      segments: translated
    }),
    finished_at: nowIso()
  });
}

