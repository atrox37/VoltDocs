import fs from "node:fs";
import path from "node:path";
import express from "express";
import multer from "multer";
import { nanoid } from "nanoid";
import { config, paths } from "../config.js";
import { getDb, nowIso } from "../db/database.js";
import { asyncRoute } from "../middleware.js";
import { registerFile } from "../services/fileRegistry.js";
import { createStoredFileName } from "../services/storage.js";
import type { AuthedRequest } from "../types/http.js";

const upload = multer({
  dest: paths.templates,
  limits: { fileSize: config.maxUploadMb * 1024 * 1024 }
});

export const templatesRouter = express.Router();

templatesRouter.get(
  "/",
  asyncRoute<AuthedRequest>(async (_req, res) => {
    const templates = getDb().prepare("SELECT * FROM templates ORDER BY created_at DESC").all();
    res.json({ templates });
  })
);

templatesRouter.post(
  "/",
  upload.single("file"),
  asyncRoute<AuthedRequest>(async (req, res) => {
    if (!req.file) {
      res.status(400).json({ error: "Missing file" });
      return;
    }
    const storedName = createStoredFileName(req.file.originalname);
    const targetPath = path.join(paths.templates, storedName);
    fs.renameSync(req.file.path, targetPath);
    const file = registerFile({
      ownerId: req.user.id,
      kind: "template",
      originalName: req.file.originalname,
      filePath: targetPath,
      mimeType: req.file.mimetype
    });
    const now = nowIso();
    const template = {
      id: nanoid(),
      file_id: file.id,
      file_name: req.file.originalname,
      language: req.body.language ? String(req.body.language) : null,
      tags_json: JSON.stringify(String(req.body.tags ?? "").split(",").map((tag) => tag.trim()).filter(Boolean)),
      uploaded_by: req.user.id,
      created_at: now,
      updated_at: now
    };
    getDb()
      .prepare(
        `INSERT INTO templates
         (id, file_id, file_name, language, tags_json, uploaded_by, created_at, updated_at)
         VALUES (@id, @file_id, @file_name, @language, @tags_json, @uploaded_by, @created_at, @updated_at)`
      )
      .run(template);
    res.status(201).json(template);
  })
);

templatesRouter.patch(
  "/:templateId",
  express.json(),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const tags = Array.isArray(req.body.tags) ? req.body.tags : undefined;
    getDb()
      .prepare("UPDATE templates SET language = COALESCE(?, language), tags_json = COALESCE(?, tags_json), updated_at = ? WHERE id = ?")
      .run(req.body.language ?? null, tags ? JSON.stringify(tags) : null, nowIso(), req.params.templateId);
    const template = getDb().prepare("SELECT * FROM templates WHERE id = ?").get(req.params.templateId);
    res.json(template);
  })
);

templatesRouter.delete(
  "/:templateId",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const template = getDb().prepare("SELECT * FROM templates WHERE id = ?").get(req.params.templateId) as { file_id: string } | undefined;
    if (!template) {
      res.status(404).json({ error: "Template not found" });
      return;
    }
    getDb().prepare("DELETE FROM templates WHERE id = ?").run(req.params.templateId);
    res.json({ ok: true });
  })
);

