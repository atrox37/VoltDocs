import fs from "node:fs";
import path from "node:path";
import express from "express";
import multer from "multer";
import { nanoid } from "nanoid";
import { config, paths } from "../config.js";
import { getDb } from "../db/database.js";
import { asyncRoute } from "../middleware.js";
import { dataPathForRecord, getFileRecord, registerFile } from "../services/fileRegistry.js";
import { createJob, getJob, listJobs } from "../services/jobs.js";
import { createStoredFileName } from "../services/storage.js";
import { exportDocx } from "../services/translation.js";
import type { AuthedRequest } from "../types/http.js";

const upload = multer({
  dest: paths.uploads,
  limits: { fileSize: config.maxUploadMb * 1024 * 1024 }
});

export const translationRouter = express.Router();

translationRouter.post(
  "/jobs",
  upload.single("file"),
  asyncRoute<AuthedRequest>(async (req, res) => {
    if (!req.file) {
      res.status(400).json({ error: "Missing file" });
      return;
    }
    const storedName = createStoredFileName(req.file.originalname);
    const targetPath = path.join(paths.uploads, storedName);
    fs.renameSync(req.file.path, targetPath);
    const file = registerFile({
      ownerId: req.user.id,
      kind: "translation-input",
      originalName: req.file.originalname,
      filePath: targetPath,
      mimeType: req.file.mimetype
    });
    const bearerToken = req.header("authorization")?.replace(/^Bearer\s+/i, "");
    const job = createJob({
      userId: req.user.id,
      type: "translation",
      inputFileId: file.id,
      payload: {
        sourceLang: String(req.body.sourceLang ?? "zh-CN"),
        targetLang: String(req.body.targetLang ?? "en-US"),
        bearerToken
      }
    });
    res.status(202).json(job);
  })
);

translationRouter.get(
  "/jobs",
  asyncRoute<AuthedRequest>(async (req, res) => {
    res.json({ jobs: listJobs(req.user.id).filter((job) => job.type === "translation") });
  })
);

translationRouter.get(
  "/jobs/:jobId",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const job = getJob(req.params.jobId);
    if (!job || job.user_id !== req.user.id) {
      res.status(404).json({ error: "Job not found" });
      return;
    }
    res.json(job);
  })
);

translationRouter.post(
  "/jobs/:jobId/export",
  express.json({ limit: "20mb" }),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const job = getJob(req.params.jobId);
    if (!job || job.user_id !== req.user.id) {
      res.status(404).json({ error: "Job not found" });
      return;
    }
    const inputFileId = job.input_file_id;
    const input = getFileRecord(inputFileId);
    if (!input) {
      res.status(404).json({ error: "Original file not found" });
      return;
    }
    const sourcePath = dataPathForRecord(input, config.dataDir);
    const outputName = `${path.parse(input.original_name).name}-translated.docx`;
    const outputPath = path.join(paths.outputs, `${nanoid(10)}-${outputName}`);
    const segments = Array.isArray(req.body.segments) ? req.body.segments : [];
    await exportDocx({
      inputPath: sourcePath,
      outputPath,
      segments: segments.map((segment: { sourceText: string; translation: string; draftTranslation?: string }) => ({
        sourceText: segment.sourceText,
        translation: segment.translation ?? segment.draftTranslation ?? ""
      }))
    });
    const file = registerFile({
      ownerId: req.user.id,
      kind: "translation-output",
      originalName: outputName,
      filePath: outputPath,
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });
    getDb().prepare("UPDATE jobs SET output_file_id = ? WHERE id = ?").run(file.id, job.id);
    res.json({ fileId: file.id, fileName: outputName, downloadUrl: `/api/files/${file.id}/download` });
  })
);

