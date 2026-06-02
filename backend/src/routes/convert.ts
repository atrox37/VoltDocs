import fs from "node:fs";
import path from "node:path";
import express from "express";
import multer from "multer";
import { config, paths } from "../config.js";
import { getDb } from "../db/database.js";
import { asyncRoute } from "../middleware.js";
import { registerFile } from "../services/fileRegistry.js";
import { createJob, getJob, listJobs } from "../services/jobs.js";
import { createStoredFileName } from "../services/storage.js";
import type { AuthedRequest } from "../types/http.js";

const upload = multer({
  dest: paths.uploads,
  limits: { fileSize: config.maxUploadMb * 1024 * 1024 }
});

export const convertRouter = express.Router();

convertRouter.post(
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
      kind: "convert-input",
      originalName: req.file.originalname,
      filePath: targetPath,
      mimeType: req.file.mimetype
    });
    const job = createJob({
      userId: req.user.id,
      type: "convert",
      inputFileId: file.id,
      payload: { outputFormat: String(req.body.outputFormat ?? "docx") }
    });
    res.status(202).json(job);
  })
);

convertRouter.get(
  "/jobs",
  asyncRoute<AuthedRequest>(async (req, res) => {
    res.json({ jobs: listJobs(req.user.id).filter((job) => job.type === "convert") });
  })
);

convertRouter.get(
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

convertRouter.delete(
  "/jobs/:jobId",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const job = getJob(req.params.jobId);
    if (!job || job.user_id !== req.user.id) {
      res.status(404).json({ error: "Job not found" });
      return;
    }
    getDb().prepare("UPDATE jobs SET status = 'cancelled' WHERE id = ? AND status = 'queued'").run(job.id);
    res.json({ ok: true });
  })
);

