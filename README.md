# TriageAI

TriageAI is a FastAPI + LangGraph complaint operations system for financial complaints. It includes:

- a public marketing site
- a user intake experience for lodging complaints
- admin and team dashboards
- document upload, OCR, and document-aware complaint processing
- live workflow traces
- benchmark and production evaluation dashboards

The app is server-rendered with Jinja templates and stores its operational state in PostgreSQL.

## What the app does

Core flow:

1. A user lodges a complaint through the intake chat.
2. Supporting documents can be uploaded during intake.
3. Documents are stored and processed locally.
4. The complaint is registered immediately.
5. The backend workflow runs:
   - document gate
   - document consistency check
   - classification
   - risk
   - root cause
   - resolution
   - compliance / routing
6. Admins can review:
   - live traces
   - complaint analytics
   - production evaluation reports
   - benchmark evaluation datasets and runs

## Main features

- LangGraph-based complaint workflow
- OpenAI or DeepSeek chat model support
- PostgreSQL + pgvector retrieval
- OCR pipeline for:
  - digital PDFs
  - scanned PDFs
  - PNG / JPG / JPEG
- session history and past complaints for end users
- production complaint evaluation with:
  - system evaluation
  - LLM judge report
- benchmark evaluation against DB-backed evaluation datasets
- live trace page backed by persisted workflow runs and steps
- website-friendly case IDs like `CASE00001`

## Tech stack

- Python 3.11+
- FastAPI
- Jinja2 templates
- SQLAlchemy
- PostgreSQL
- pgvector
- LangGraph / LangChain
- OpenTelemetry-based local workflow tracing
- optional LangSmith tracing for LangChain / LangGraph runs

## Repository layout

```text
app/
  agents/           Specialist agents and intake logic
  api/              JSON and integration routes
  db/               SQLAlchemy models and DB initialization
  documents/        Upload, OCR, extraction, and document processing
  evals/            Benchmark datasets, judge logic, eval runners
  knowledge/        Mock bank knowledge pack and taxonomy
  observability/    Workflow logging, persistence, tracing helpers
  orchestrator/     LangGraph workflow and state
  retrieval/        pgvector ingestion and retrieval indexes
  schemas/          Pydantic schemas
  static/           CSS and JS
  templates/        Jinja templates
  ui/               HTML routes and page context builders
  utils/            Shared helpers

main.py             FastAPI entry point
docker-compose.yml  Local Postgres + app
complaints.csv      Optional CFPB dataset used for retrieval / evaluation seeding
```

## Prerequisites

Required:

- Python 3.11 or newer
- PostgreSQL with pgvector
- one LLM provider configured:
  - OpenAI, or
  - DeepSeek

Recommended local tools:

- `uv` for dependency management
- Docker for local Postgres

For OCR:

- `tesseract`
- `poppler` / `poppler-utils`

## Environment setup

Copy the example file:

```bash
cp .env.example .env
```

Minimum variables to set:

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/complaints
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

If using DeepSeek instead:

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
```

Common optional variables:

- `OPENAI_CHAT_MODEL`
- `DEEPSEEK_CHAT_MODEL`
- `EMBEDDING_PROVIDER=huggingface` or `openai`
- `HF_EMBEDDING_MODEL`
- `HF_DEVICE`
- `LOG_LEVEL`
- `SQL_ECHO`
- `TRACE_INTAKE_TO_LANGSMITH`
- `LANGCHAIN_TRACING_V2`
- `LANGCHAIN_API_KEY`
- `LANGCHAIN_PROJECT`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`

Important:

- `main.py` loads `.env` automatically at startup.
- Do not commit real API keys. If your `.env` already contains secrets, rotate them.

## Install dependencies

### Option 1: uv

```bash
uv sync
```

Run commands with `uv run`, for example:

```bash
uv run python -m uvicorn main:app --reload
```

### Option 2: pip + venv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Install OCR dependencies

### macOS

```bash
brew install tesseract poppler
```

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

### Amazon Linux / RHEL family

```bash
sudo yum install -y tesseract poppler-utils
```

Verify:

```bash
tesseract --version
pdftoppm -v
```

## Run PostgreSQL

### Local Docker DB only

```bash
docker compose up db -d
```

Default local DB URL matches:

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/complaints
```

### Run app + DB in Docker

```bash
docker compose up --build
```

Detached:

```bash
docker compose up --build -d
docker compose logs -f app
```

In Docker, the app service uses:

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/complaints
```

## Run the app locally

Start the server:

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

- public site: `http://127.0.0.1:8000/`
- login: `http://127.0.0.1:8000/login`

On startup the app will:

- initialize logging
- initialize tracing
- create / backfill DB schema
- seed default users
- backfill public case IDs if needed

## Seeded users

The app seeds these default users automatically:

### Admin

- email: `admin@triage.ai`
- password: `admin123`

### End user

- email: `user@triage.ai`
- password: `user123`

### Team accounts

Multiple team accounts are seeded automatically, for example:

- `creditcard@triage.ai`
- `payments@triage.ai`
- `fraudaccessops@triage.ai`

Passwords follow the pattern:

```text
<local-part>123
```

Example:

- email: `creditcard@triage.ai`
- password: `creditcard123`

## Main pages

### Public pages

- `/` — platform landing page
- `/pain-points`
- `/agentic-solution`
- `/brand`

### User pages

- `/profile`
- `/complaints/new`
- `/past-complaints`
- `/resolutions`

### Admin pages

- `/` — admin overview for admins, complaint dashboard for authenticated users
- `/queue`
- `/analytics`
- `/evaluation`
- `/trace/latest`
- `/team`
- `/settings`

## Documents and OCR

Uploaded documents are treated as first-class complaint artifacts.

Current behavior:

- files upload during intake
- documents are stored locally
- OCR / extraction runs in the background
- specialist agents wait on the document gate when documents are attached
- document consistency checks run before supervisor decisions

Supported:

- digital PDFs via direct text extraction
- scanned PDFs via page rendering + OCR
- images via Tesseract OCR

Storage defaults:

- uploaded files: under `app_data/uploads` unless overridden
- document metadata / artifacts: PostgreSQL tables

## Retrieval ingestion from CFPB data

If you want complaint retrieval and richer evaluation data, place a CFPB-style CSV at:

```text
complaints.csv
```

Then run ingestion:

```bash
python -m app.retrieval.ingest --sample 5000
```

Larger run:

```bash
python -m app.retrieval.ingest --sample 50000
```

Notes:

- sampling is stratified by `Product × Issue`
- PII redaction is applied to narratives before storage
- vector dimensions depend on your configured embedding provider
- set your embedding provider before first ingestion

## Evaluation

The repo now has two evaluation layers:

### 1. Benchmark evaluation

DB-backed benchmark datasets and runs live under `/evaluation`.

To seed a CFPB-backed benchmark dataset:

```bash
python -m app.evals.run_evals --seed-cfpb-benchmark --sample-size 500
```

To run the latest DB-backed benchmark:

```bash
python -m app.evals.run_evals
```

Or run a specific dataset:

```bash
python -m app.evals.run_evals --benchmark-dataset-id <dataset_id>
```

### 2. Production evaluation

Real complaints are evaluated after processing.

The admin analytics page shows:

- summary counts
- recent complaint evaluation reports
- per-complaint evaluation detail pages

Each production evaluation stores:

- normalized system prediction
- system assessment
- LLM judge output
- reasoning and disagreement signals

## Live traces

Admins can open:

```text
/trace/latest
```

The trace page supports live updates while a complaint is processing. It streams from persisted `workflow_runs` and `workflow_steps`.

## LangSmith and tracing

The app supports two different tracing layers:

### Local workflow tracing

Always available in-repo via OpenTelemetry helpers and persisted workflow tables.

### LangSmith

Optional. Enable it with environment variables:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=complaint-agent
```

Notes:

- intake tracing to LangSmith is separately controlled
- LangSmith is not required to run the app

## ElevenLabs integration

This repo includes an ElevenLabs-compatible custom LLM integration for intake and optional TTS.

Relevant env vars:

- `ELEVENLABS_API_KEY`
- `ELEVENLABS_CUSTOM_LLM_SECRET`
- `ELEVENLABS_INTAKE_REQUIRE_USER`
- `ELEVENLABS_VOICE_ID`

Relevant route base:

```text
/api/v1/integrations/elevenlabs
```

## Jira integration

Optional Jira fields in `.env`:

- `JIRA_BASE_URL`
- `JIRA_USER_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`
- `JIRA_ASSIGNEE_ID`

## Database notes

The app uses a single PostgreSQL database with multiple domains:

- production complaint processing
- document storage / extraction
- evaluation / benchmarking
- workflow tracing

Tables are created and backfilled by `init_db()` on startup.

Important behaviors already handled:

- legacy rows get `CASE00001`-style public case IDs
- default users are seeded
- newer schema columns are added if missing

## Development workflow

Useful commands:

```bash
python -m uvicorn main:app --reload
python -m app.retrieval.ingest --sample 5000
python -m app.evals.run_evals --seed-cfpb-benchmark --sample-size 500
python -m compileall app
```

## Troubleshooting

### App starts but pages fail because DB is down

Make sure Postgres is running:

```bash
docker compose ps
```

### Scanned PDFs do not process

Check:

```bash
tesseract --version
pdftoppm -v
```

If `pdftoppm` is missing, install Poppler.

### Evaluation page is empty

You may not have run any benchmark seeding or benchmark runs yet.

Seed one:

```bash
python -m app.evals.run_evals --seed-cfpb-benchmark --sample-size 500
```

### Production analytics evaluation is empty

Only complaints processed after the production evaluation system was added will automatically have stored evaluation reports unless you backfill them.

### Complaint documents appear in intake but not in past complaints

Make sure:

- the document upload completed successfully
- the complaint was finalized
- the app has been restarted after schema changes if this is an older DB

### Theme / public page contrast issues

Public marketing pages force light mode. Authenticated app pages still support theme toggle.

## Testing / sanity checks

At minimum, before shipping changes:

```bash
python -m py_compile main.py
python -m compileall app
```

If you use local modifications heavily, also validate the target flows manually:

- user intake
- document upload
- complaint submit
- admin queue
- analytics
- evaluation
- live trace

## License / usage

No license file is currently included in this repository. Treat usage and redistribution as private unless you add an explicit license.
