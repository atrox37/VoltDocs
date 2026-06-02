import path from "node:path";

export const config = {
  port: Number(process.env.PORT ?? 8080),
  dataDir: path.resolve(process.env.DATA_DIR ?? path.join(process.cwd(), "data")),
  databasePath: path.resolve(
    process.env.DATABASE_PATH ?? path.join(process.env.DATA_DIR ?? path.join(process.cwd(), "data"), "db", "voltdocs.db")
  ),
  pandocPath: process.env.PANDOC_PATH ?? "pandoc",
  pandocMaxConcurrency: Number(process.env.PANDOC_MAX_CONCURRENCY ?? 1),
  pandocTimeoutSeconds: Number(process.env.PANDOC_TIMEOUT_SECONDS ?? 300),
  maxUploadMb: Number(process.env.MAX_UPLOAD_MB ?? 50),
  translationLambdaUrl: process.env.TRANSLATION_LAMBDA_URL ?? "",
  glossaryMaxTerms: Number(process.env.GLOSSARY_MAX_TERMS_PER_REQUEST ?? 100),
  glossaryMaxPromptChars: Number(process.env.GLOSSARY_MAX_PROMPT_CHARS ?? 12000),
  translationBatchSegments: Number(process.env.TRANSLATION_BATCH_SEGMENTS ?? 30),
  requireAuth: process.env.REQUIRE_AUTH === "true"
};

export const paths = {
  db: path.join(config.dataDir, "db"),
  templates: path.join(config.dataDir, "templates"),
  uploads: path.join(config.dataDir, "uploads"),
  outputs: path.join(config.dataDir, "outputs"),
  archives: path.join(config.dataDir, "archives"),
  jobs: path.join(config.dataDir, "jobs")
};

