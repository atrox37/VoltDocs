import express from "express";
import { nanoid } from "nanoid";
import { z } from "zod";
import { getDb, nowIso } from "../db/database.js";
import { asyncRoute } from "../middleware.js";
import type { AuthedRequest } from "../types/http.js";

export const glossaryRouter = express.Router();

const termSchema = z.object({
  sourceLang: z.string().default("zh-CN"),
  targetLang: z.string().default("en-US"),
  sourceTerm: z.string().min(1),
  targetTerm: z.string().min(1),
  domain: z.string().optional().nullable(),
  context: z.string().optional().nullable(),
  required: z.boolean().optional().default(false),
  forbiddenTerms: z.array(z.string()).optional().default([]),
  enabled: z.boolean().optional().default(true),
  priority: z.number().int().optional().default(0)
});

function audit(action: string, termId: string | null, beforeValue: unknown, afterValue: unknown, actor: string) {
  getDb()
    .prepare(
      `INSERT INTO glossary_audit_logs
       (id, term_id, action, before_json, after_json, actor, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    )
    .run(nanoid(), termId, action, beforeValue ? JSON.stringify(beforeValue) : null, afterValue ? JSON.stringify(afterValue) : null, actor, nowIso());
}

glossaryRouter.get(
  "/",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const { sourceLang, targetLang, q } = req.query;
    const rows = getDb()
      .prepare(
        `SELECT * FROM glossary_terms
         WHERE (? IS NULL OR source_lang = ?)
           AND (? IS NULL OR target_lang = ?)
           AND (? IS NULL OR source_term LIKE ? OR target_term LIKE ?)
         ORDER BY priority DESC, updated_at DESC
         LIMIT 500`
      )
      .all(
        sourceLang ?? null,
        sourceLang ?? null,
        targetLang ?? null,
        targetLang ?? null,
        q ? `%${q}%` : null,
        q ? `%${q}%` : null,
        q ? `%${q}%` : null
      );
    res.json({ terms: rows });
  })
);

glossaryRouter.post(
  "/terms",
  express.json(),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const input = termSchema.parse(req.body);
    const now = nowIso();
    const term = {
      id: nanoid(),
      source_lang: input.sourceLang,
      target_lang: input.targetLang,
      source_term: input.sourceTerm,
      target_term: input.targetTerm,
      domain: input.domain ?? null,
      context: input.context ?? null,
      required: input.required ? 1 : 0,
      forbidden_terms_json: JSON.stringify(input.forbiddenTerms),
      enabled: input.enabled ? 1 : 0,
      priority: input.priority,
      created_by: req.user.id,
      created_at: now,
      updated_at: now
    };
    getDb()
      .prepare(
        `INSERT INTO glossary_terms
         (id, source_lang, target_lang, source_term, target_term, domain, context, required, forbidden_terms_json, enabled, priority, created_by, created_at, updated_at)
         VALUES (@id, @source_lang, @target_lang, @source_term, @target_term, @domain, @context, @required, @forbidden_terms_json, @enabled, @priority, @created_by, @created_at, @updated_at)`
      )
      .run(term);
    audit("create", term.id, null, term, req.user.id);
    res.status(201).json(term);
  })
);

glossaryRouter.patch(
  "/terms/:termId",
  express.json(),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const before = getDb().prepare("SELECT * FROM glossary_terms WHERE id = ?").get(req.params.termId);
    if (!before) {
      res.status(404).json({ error: "Term not found" });
      return;
    }
    getDb()
      .prepare(
        `UPDATE glossary_terms
         SET target_term = COALESCE(?, target_term),
             context = COALESCE(?, context),
             enabled = COALESCE(?, enabled),
             required = COALESCE(?, required),
             priority = COALESCE(?, priority),
             updated_at = ?
         WHERE id = ?`
      )
      .run(
        req.body.targetTerm ?? null,
        req.body.context ?? null,
        typeof req.body.enabled === "boolean" ? (req.body.enabled ? 1 : 0) : null,
        typeof req.body.required === "boolean" ? (req.body.required ? 1 : 0) : null,
        Number.isInteger(req.body.priority) ? req.body.priority : null,
        nowIso(),
        req.params.termId
      );
    const after = getDb().prepare("SELECT * FROM glossary_terms WHERE id = ?").get(req.params.termId);
    audit("update", req.params.termId, before, after, req.user.id);
    res.json(after);
  })
);

glossaryRouter.delete(
  "/terms/:termId",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const before = getDb().prepare("SELECT * FROM glossary_terms WHERE id = ?").get(req.params.termId);
    if (!before) {
      res.status(404).json({ error: "Term not found" });
      return;
    }
    getDb().prepare("DELETE FROM glossary_terms WHERE id = ?").run(req.params.termId);
    audit("delete", req.params.termId, before, null, req.user.id);
    res.json({ ok: true });
  })
);

function parseCsv(text: string) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const [headerLine, ...body] = lines;
  const headers = headerLine.split(",").map((value) => value.trim());
  return body.map((line, index) => {
    const values = line.split(",").map((value) => value.trim());
    const row = Object.fromEntries(headers.map((header, i) => [header, values[i] ?? ""]));
    return { line: index + 2, row };
  });
}

glossaryRouter.post(
  "/import/preview",
  express.text({ type: "*/*", limit: "10mb" }),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const rows = parseCsv(String(req.body ?? ""));
    const errors: Array<{ line: number; message: string }> = [];
    const valid = rows.flatMap(({ line, row }) => {
      if (!row.sourceTerm || !row.targetTerm) {
        errors.push({ line, message: "sourceTerm 和 targetTerm 必填" });
        return [];
      }
      return [{
        line,
        sourceLang: row.sourceLang || "zh-CN",
        targetLang: row.targetLang || "en-US",
        sourceTerm: row.sourceTerm,
        targetTerm: row.targetTerm,
        context: row.context || "",
        priority: Number(row.priority || 0)
      }];
    });
    res.json({ total: rows.length, validCount: valid.length, errorCount: errors.length, valid, errors });
  })
);

glossaryRouter.post(
  "/import/commit",
  express.json({ limit: "10mb" }),
  asyncRoute<AuthedRequest>(async (req, res) => {
    const rows = Array.isArray(req.body.rows) ? req.body.rows : [];
    const insert = getDb().prepare(
      `INSERT INTO glossary_terms
       (id, source_lang, target_lang, source_term, target_term, domain, context, required, forbidden_terms_json, enabled, priority, created_by, created_at, updated_at)
       VALUES (@id, @source_lang, @target_lang, @source_term, @target_term, NULL, @context, 0, '[]', 1, @priority, @created_by, @created_at, @updated_at)
       ON CONFLICT(source_lang, target_lang, source_term)
       DO UPDATE SET target_term = excluded.target_term, context = excluded.context, priority = excluded.priority, updated_at = excluded.updated_at`
    );
    const now = nowIso();
    const tx = getDb().transaction(() => {
      for (const row of rows) {
        insert.run({
          id: nanoid(),
          source_lang: row.sourceLang || "zh-CN",
          target_lang: row.targetLang || "en-US",
          source_term: row.sourceTerm,
          target_term: row.targetTerm,
          context: row.context ?? null,
          priority: Number(row.priority ?? 0),
          created_by: req.user.id,
          created_at: now,
          updated_at: now
        });
      }
    });
    tx();
    audit("import", null, null, { count: rows.length }, req.user.id);
    res.json({ imported: rows.length });
  })
);

glossaryRouter.get(
  "/audit-logs",
  asyncRoute<AuthedRequest>(async (_req, res) => {
    const logs = getDb().prepare("SELECT * FROM glossary_audit_logs ORDER BY created_at DESC LIMIT 100").all();
    res.json({ logs });
  })
);

