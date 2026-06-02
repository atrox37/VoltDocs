import express from "express";
import cors from "cors";
import { config } from "./config.js";
import { getDb } from "./db/database.js";
import { authMiddleware } from "./middleware.js";
import { ensureRuntimeDirs } from "./services/storage.js";
import { convertRouter } from "./routes/convert.js";
import { filesRouter } from "./routes/files.js";
import { glossaryRouter } from "./routes/glossary.js";
import { reviewsRouter } from "./routes/reviews.js";
import { templatesRouter } from "./routes/templates.js";
import { translationRouter } from "./routes/translation.js";

ensureRuntimeDirs();
getDb();

const app = express();
app.use(cors());

app.get("/api/health", (_req, res) => {
  res.json({
    ok: true,
    version: "0.1.1",
    dataDir: config.dataDir,
    pandocMaxConcurrency: config.pandocMaxConcurrency
  });
});

app.use("/api", authMiddleware);
app.use("/api/convert", convertRouter);
app.use("/api/files", filesRouter);
app.use("/api/glossary", glossaryRouter);
app.use("/api/reviews", reviewsRouter);
app.use("/api/templates", templatesRouter);
app.use("/api/translation", translationRouter);

app.use((error: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  const message = error instanceof Error ? error.message : String(error);
  res.status(500).json({ error: message });
});

app.listen(config.port, () => {
  console.log(`VoltDocs API listening on :${config.port}`);
});

