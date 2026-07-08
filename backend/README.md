# VoltDocs Backend

FastAPI-based backend providing document translation, conversion, glossary management, and authentication.

## Quick Start

```powershell
cd backend
poetry env use 3.11
poetry install
copy .env.example .env
poetry run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Default local API: http://127.0.0.1:8080

## Project Structure

```
backend/
├── auth/
│   ├── cognito.py        # Cognito OAuth client
│   ├── middleware.py     # Authentication middleware
│   ├── routes.py         # Auth endpoints
│   └── session.py        # In-memory session store
├── routes/
│   ├── convert.py        # Document conversion (MD ↔ DOCX)
│   ├── translation.py    # Document translation
│   ├── glossary.py       # Glossary management
│   ├── files.py          # File download/upload
│   ├── templates.py      # Template management
│   ├── users.py          # User management
│   ├── settings.py       # User settings
│   ├── dashboard.py      # Dashboard statistics
│   ├── quality.py        # QA configuration
│   └── health.py         # Health check
├── services/
│   ├── docx_parser.py           # Parse Word documents
│   ├── docx_exporter.py         # Export translated Word
│   ├── docx_security.py         # Security checks for DOCX
│   ├── docx/                    # DOCX helper modules
│   │   ├── fields.py            # Field code handling
│   │   ├── markup.py            # Inline format markers
│   ├── excel_parser.py          # Parse Excel files
│   ├── excel_exporter.py        # Export translated Excel
│   ├── md_parser.py             # Parse Markdown
│   ├── md_exporter.py           # Export Markdown
│   ├── translation.py           # Translation orchestration
│   ├── glossary_matcher.py      # Terminology matching
│   ├── tm.py                    # Translation memory
│   ├── prompt.py                # AI prompt construction
│   ├── bedrock.py               # AWS Bedrock client
│   ├── qa_*.py                  # Quality assurance modules
│   ├── qa_hybrid.py             # Hybrid QA evaluation
│   ├── qa_repair_ai.py          # AI-based repair
│   ├── access_control.py        # RBAC helpers
│   ├── storage.py               # File storage helpers
│   └── pandoc.py                # Pandoc wrapper
├── tests/                       # Pytest coverage
├── config.py                    # Configuration management
├── database.py                  # SQLite with migrations
└── main.py                      # FastAPI application
```

## Database Schema

### Core Tables

| Table | Description |
|-------|-------------|
| `files` | Uploaded file metadata |
| `jobs` | Translation/conversion job queue |
| `job_segments` | Individual segment translations |
| `glossary_terms` | Bilingual terminology |
| `glossary_audit_logs` | Term change history |
| `translation_memory` | Cached translations |
| `user_settings` | Per-user preferences |
| `user_roles` | Role assignments |
| `role_audit_log` | Role change history |

### Roles

- `super_admin` - Full access, can manage user roles
- `manager` - Can manage glossary and view logs
- `user` - Basic translation access

## Document Processing

### Word (.docx)

Uses `lxml` to directly manipulate internal XML:

1. **Parsing**: Reads `word/document.xml`, headers (`header*.xml`), footers (`footer*.xml`)
2. **IR Build**: Converts document content into a document-oriented intermediate representation with stable segment ids and location metadata
3. **Inline Formats**: `**bold**`, `*italic*`, `~~strikethrough~~`
4. **Translation Payload**: Sends only segment text plus per-segment glossary entries to the model
5. **Export**: Preserves runs, styles, images, tables

**Key Files:**
- `services/docx_parser.py` - Extracts text with style info
- `services/docx_exporter.py` - Reconstructs document with translations

### Excel (.xlsx)

Uses `openpyxl`:

1. **Parsing**: Iterates worksheets → rows → cells
2. **Segment Types**: `cell`, `sheet_title`
3. **Context**: Sheet name, cell coordinate (e.g., A1)
4. **Deduplication**: Collapses repeated source cells before translation, then fans translations back out
5. **Export**: Writes translations back to cells, renames sheets

**Key Files:**
- `services/excel_parser.py` - Extracts cell content
- `services/excel_exporter.py` - Writes translations to cells

### Batch Limits

| Scope | Max Bytes | Max Segments | Notes |
|-------|-----------|--------------|-------|
| Global config default | 5000 | 40 | Values exposed through `TRANSLATION_BATCH_MAX_BYTES` and `TRANSLATION_BATCH_MAX_SEGMENTS` |
| Runtime path for `.docx` / `.xlsx` / `.md` | Caller-provided ceiling | Up to 50 | Current production path uses coarse simple batching to reduce request count and latency |

## Translation Flow

```
1. Upload File
      ↓
2. Parse (docx_parser / excel_parser / md_parser)
      ↓
3. Build file-specific IR and extract translatable segments with context (sheet, cell, style_name, document location)
       ↓
4. Load glossary terms for source/target language pair
       ↓
5. Deduplicate repeated spreadsheet text when applicable
       ↓
6. Split into coarse byte-bounded batches
       ↓
7. For each batch:
   a. Check translation memory (TM)
   b. Call AWS Bedrock (Nova model)
   c. Finalize text (marker cleanup, circled prefix preservation, heading punctuation normalization)
   d. QA check (7 rules + optional AI evaluation)
   e. Store to TM if QA passed
       ↓
8. Render/export (docx_exporter / excel_exporter / md_exporter)
       ↓
9. Return translated file
```

## QA Quality Checks

Automated checks on each segment:

| Check | Description |
|-------|-------------|
| Non-empty | Translation is not blank |
| Number match | Numbers from source appear in translation |
| Format preservation | Bold/italic/strikethrough markers preserved |
| Length reasonable | Translation length is proportional |
| Language correctness | Output is in target language |
| Glossary compliance | Required terms used |
| Punctuation | Correct punctuation for target language |

## Prompt and Output Rules

- The model receives only the segment text that actually needs translation, plus the glossary entries relevant to that segment.
- The system prompt explicitly forbids metadata wrappers such as `translated text=` / `translation=` / labels / quotes around the answer.
- The system prompt requires target-language punctuation, so English output should not keep Chinese sentence punctuation by default.
- English heading output normalizes common Chinese heading punctuation such as `1、` to `1.` during finalization.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Server port | 8080 |
| `DATA_DIR` | Data directory | `./data` |
| `REQUIRE_AUTH` | Enable auth | false |
| `INITIAL_ADMIN_EMAIL` | First super admin | - |
| `BEDROCK_MODEL_ID` | Translation model | `us.amazon.nova-lite-v1:0` |
| `BEDROCK_REGION` | AWS region | `us-east-1` |
| `BEDROCK_AWS_PROFILE` | AWS profile | - |
| `QA_AI_ENABLED` | AI QA | true |
| `QA_AI_MODEL_ID` | QA model | `us.amazon.nova-micro-v1:0` |
| `COGNITO_DOMAIN` | Cognito domain | - |
| `COGNITO_CLIENT_ID` | Client ID | - |
| `COGNITO_CLIENT_SECRET` | Client secret | - |
| `COGNITO_REDIRECT_URI` | OAuth callback | - |
| `FRONTEND_URL` | Frontend URL | `http://localhost:5173` |

## Running Tests

```powershell
cd backend
poetry run pytest tests/ -q
```

## Notes

- Python version pinned to 3.11.x
- Uses in-project virtualenv at `backend/.venv`
- SQLite with WAL mode for concurrent access
- Schema migrations in `database.py`
- Session sweep runs every 5 minutes
