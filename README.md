# VoltDocs Web

V0.1.1 Web edition for single-server Docker deployment.

## Structure

```text
frontend/     Vite React web client
backend/      Express API, local storage, job queue, Pandoc runner
infra/        Docker and Nginx deployment files
docs/         Product and implementation notes
```

## Local Development

```bash
pnpm install
pnpm --dir backend install
pnpm --dir frontend install
pnpm dev
```

Frontend: http://localhost:5173  
Backend: http://localhost:8080

## Runtime Data

The backend writes runtime data to `DATA_DIR`, defaulting to `./data`:

```text
data/
├── db/
├── templates/
├── uploads/
├── outputs/
├── archives/
└── jobs/
```

Do not store runtime data inside a Docker image. Mount it as a volume.

