# TriageAI

TriageAI is a complaint management system for financial complaints. It includes:

- admin and team dashboards
- conversational style intake for lodging complaints (chat and optional voice)
- document upload, OCR, and document-aware complaint processing
- Agentic AI for processing complaints
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

## Install dependencies

### Option 1: uv

```bash
uv sync
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

## Run PostgreSQL

### Local Docker DB only

```bash
docker compose up db -d
```

For Server deployment run both app and db

```bash
docker compose up --build -d
docker compose logs -f app
```

## Run the app locally

Start the server:

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open the **Lodge complaint** page from the app navigation (or the route your UI exposes for lodging a complaint). There is no separate voice server process: voice uses the same FastAPI app.

### Voice mode (Lodge intake)

The Lodge page supports **chat** and an optional **Voice** mode (toggle on the page). Voice uses the browser’s **Web Speech API** for speech-to-text and, if configured, **ElevenLabs** for text-to-speech replies.

1. **Start a session** on the Lodge page (same as chat).
2. Enable **Voice** in the UI, then use the microphone control to start voice turns (pause after speaking to send; the agent can reply aloud when TTS is configured).

**Browser / security context**

- The microphone is only available in a **secure context**. That usually means:
  - **`http://localhost:<port>`** or **`http://127.0.0.1:<port>`** — OK for development.
  - Opening the app via **another hostname**, **another machine on the LAN**, or plain **`http://` on a non-loopback IP** may block the mic until you use **HTTPS**.
- If speech recognition fails with a message about **HTTPS or localhost**, use local HTTPS below or access the app only via `localhost` / `127.0.0.1`.

**Local HTTPS (recommended when the mic is blocked on HTTP)**

From the repo root, generate trusted certs once (see comments in the script), then:

```bash
./scripts/dev_https.sh
```

By default this serves **`https://127.0.0.1:8001`** (override `PORT` / `HOST` if needed). Prerequisites: `mkcert` and certificate files under `.certs/` — see the header comments in [`scripts/dev_https.sh`](scripts/dev_https.sh).

**Spoken agent replies (optional)**

Set in `.env` (see [`.env.example`](.env.example)):

- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID` (or related env names listed in `.env.example`)

Without these, Voice mode can still use the browser for recognition; spoken replies are disabled until ElevenLabs is configured.

**ElevenLabs Conversational AI (optional, external agent)**

To connect an ElevenLabs agent with Custom LLM to this backend, point its base URL at your public HTTPS API, for example:

`https://<your-host>/api/v1/integrations/elevenlabs`

Details and optional Bearer protection are documented in `.env.example` (`ELEVENLABS_CUSTOM_LLM_SECRET`, `ELEVENLABS_INTAKE_REQUIRE_USER`, etc.).

### Admin

- email: `admin@triage.ai`
- password: `admin123`

### End user

- email: `user@triage.ai`
- password: `user123`

### Team accounts

Multiple team accounts are seeded automatically : 

Passwords follow the pattern: (Team Credentials)[https://github.com/ayman-tech/Multi-Agent-Complaint-System/wiki/Team-Credentials]

password : `<local-part>123`

## License / usage

No license file is currently included in this repository. Treat usage and redistribution as private unless you add an explicit license.
