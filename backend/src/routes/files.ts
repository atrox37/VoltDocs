import express from "express";
import { config } from "../config.js";
import { asyncRoute } from "../middleware.js";
import { dataPathForRecord, getFileRecord } from "../services/fileRegistry.js";
import type { AuthedRequest } from "../types/http.js";

export const filesRouter = express.Router();

filesRouter.get(
  "/:fileId/download",
  asyncRoute<AuthedRequest>(async (req, res) => {
    const record = getFileRecord(req.params.fileId);
    if (!record) {
      res.status(404).json({ error: "File not found" });
      return;
    }
    if (record.owner_id !== req.user.id && record.owner_id !== "system") {
      res.status(403).json({ error: "Forbidden" });
      return;
    }
    res.download(dataPathForRecord(record, config.dataDir), record.original_name);
  })
);

