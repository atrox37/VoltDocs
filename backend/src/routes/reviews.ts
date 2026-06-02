import express from "express";
import { nanoid } from "nanoid";
import { getDb, nowIso } from "../db/database.js";
import { asyncRoute } from "../middleware.js";
import type { AuthedRequest } from "../types/http.js";

export const reviewsRouter = express.Router();

reviewsRouter.get(
  "/",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const reviews = getDb()
      .prepare("SELECT * FROM review_records WHERE user_id = ? ORDER BY updated_at DESC LIMIT 100")
      .all(req.user.id);
    res.json({ reviews });
  })
);

reviewsRouter.post(
  "/",
  express.json({ limit: "20mb" }),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const now = nowIso();
    const record = {
      id: nanoid(),
      user_id: req.user.id,
      source_file_id: req.body.sourceFileId ?? null,
      translated_file_id: req.body.translatedFileId ?? null,
      file_name: String(req.body.fileName ?? "review.docx"),
      source_lang: String(req.body.sourceLang ?? "zh-CN"),
      target_lang: String(req.body.targetLang ?? "en-US"),
      status: String(req.body.status ?? "reviewing"),
      segments_json: JSON.stringify(req.body.segments ?? []),
      created_at: now,
      updated_at: now
    };
    getDb()
      .prepare(
        `INSERT INTO review_records
         (id, user_id, source_file_id, translated_file_id, file_name, source_lang, target_lang, status, segments_json, created_at, updated_at)
         VALUES (@id, @user_id, @source_file_id, @translated_file_id, @file_name, @source_lang, @target_lang, @status, @segments_json, @created_at, @updated_at)`
      )
      .run(record);
    res.status(201).json(record);
  })
);

reviewsRouter.patch(
  "/:reviewId",
  express.json({ limit: "20mb" }),
  asyncRoute<AuthedRequest>(async (req, res) => {
    getDb()
      .prepare("UPDATE review_records SET status = COALESCE(?, status), segments_json = COALESCE(?, segments_json), updated_at = ? WHERE id = ? AND user_id = ?")
      .run(req.body.status ?? null, req.body.segments ? JSON.stringify(req.body.segments) : null, nowIso(), req.params.reviewId, req.user.id);
    const record = getDb().prepare("SELECT * FROM review_records WHERE id = ? AND user_id = ?").get(req.params.reviewId, req.user.id);
    res.json(record);
  })
);

