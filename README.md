# VoltDocs

VoltDocs is an internal document processing platform for Voltage Energy. It supports document translation, Markdown to Word conversion, glossary management, role-based access control, and Docker-based deployment.

## Core Features

- **Translate documents** - Support for `docx`, `xlsx`, and `md` files while preserving structure
- **Quality Assurance** - Automated QA checks after translation with manual review workflow
- **Document Conversion** - Convert Markdown into Word documents with reusable templates
- **Glossary Management** - Manage bilingual glossary terms and enforce them during translation
- **Role-Based Access Control** - Three-level permission system (Super Admin / Manager / User)
- **Authentication** - Cognito-backed authentication with session management

## Tech Stack

- **Frontend**: React 18, TypeScript, Ant Design, Vite
- **Backend**: Python 3.11.x, FastAPI, SQLite (WAL mode)
- **AI**: AWS Bedrock (Nova models)
- **Conversion**: Pandoc
- **Excel Processing**: openpyxl
- **Word Processing**: lxml (direct XML manipulation)
- **Deployment**: Docker Compose, Nginx

## Project Structure

```
VoltDocs/
├── backend/           # FastAPI backend
│   ├── auth/          # Cognito authentication & session management
│   ├── routes/        # API endpoints
│   ├── services/      # Core business logic
│   │   ├── docx_parser.py      # Word document parsing
│   │   ├── docx_exporter.py    # Word document export
│   │   ├── excel_parser.py     # Excel parsing
│   │   ├── excel_exporter.py   # Excel export
│   │   ├── translation.py      # Translation orchestration
│   │   ├── glossary_matcher.py # Terminology matching
│   │   ├── tm.py               # Translation memory
│   │   ├── qa_*.py             # Quality assurance
│   │   └── bedrock.py          # AWS Bedrock integration
│   ├── tests/         # Pytest coverage
│   ├── config.py      # Environment-backed configuration
│   ├── database.py    # SQLite with schema migrations
│   └── main.py        # FastAPI application entrypoint
├── frontend/          # React single-page application
├── deploy/            # Deployment scripts and documentation
├── docs/              # User guides and documentation
└── docker-compose.yml # Docker orchestration
```

## Supported File Formats

| Format | Extension | Translation | Conversion |
|--------|-----------|-------------|------------|
| Word Document | .docx | ✅ | MD → DOCX |
| Excel Spreadsheet | .xlsx | ✅ | - |
| Markdown | .md | ✅ | MD → DOCX |

### Document Processing Details

**Word (.docx) Translation:**
- Parses internal XML structure (document.xml, headers, footers)
- Preserves: bold, italic, strikethrough, fonts, colors, images, tables
- Handles: field codes, style inheritance, page layouts

**Excel (.xlsx) Translation:**
- Parses worksheets and cell content
- Preserves: formulas, merged cells, table styles, sheet names
- Context: sheet name, cell coordinate (e.g., A1, B2)

**Markdown Translation:**
- Basic paragraph and heading translation
- Supports inline formatting markers

## Local Development

### Prerequisites

- Python 3.11.x
- Node.js 20+
- pnpm
- Poetry 2.x
- Pandoc
- AWS credentials for Bedrock (via environment or `BEDROCK_AWS_PROFILE`)

### Install and Run

```bash
# Install frontend dependencies
pnpm install
cd frontend && pnpm install && cd ..

# Setup backend
cp backend/.env.example backend/.env
poetry --directory backend install

# Run both frontend and backend
pnpm dev
```

### Run Backend Only

```bash
cd backend
poetry env use 3.11
poetry install
poetry run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

> **Important:** Backend uses in-project virtualenv at `backend/.venv`. If using older Python version, delete `.venv` and recreate with `poetry env use 3.11`.

### Run Frontend Only

```bash
cd frontend
pnpm dev
```

## Testing

```bash
# All tests
pnpm test

# Backend only
cd backend
poetry run pytest tests/ -q
```

## Configuration

Main backend settings in `backend/.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Backend port | 8080 |
| `DATA_DIR` | Data directory | `./data` |
| `REQUIRE_AUTH` | Enable authentication | false |
| `INITIAL_ADMIN_EMAIL` | First super admin email | - |
| `BEDROCK_MODEL_ID` | Translation model | `us.amazon.nova-lite-v1:0` |
| `BEDROCK_REGION` | AWS region | `us-east-1` |
| `TRANSLATION_BATCH_MAX_BYTES` | Max bytes per batch | 5000 |
| `TRANSLATION_BATCH_MAX_SEGMENTS` | Max segments per batch | 40 |
| `QA_AI_ENABLED` | Enable AI QA | true |
| `COGNITO_DOMAIN` | Cognito domain | - |
| `COGNITO_CLIENT_ID` | Cognito app client ID | - |

See `backend/config.py` for the full list.

## Documentation

- [backend/README.md](backend/README.md) - Backend development guide
- [deploy/README.md](deploy/README.md) - Production deployment
- [docs/voltdocs-user-guide.md](docs/voltdocs-user-guide.md) - User guide