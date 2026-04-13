# AI Agent for Complaint Classification

FastAPI service that runs an **agentic LangGraph** workflow over consumer complaints as a **company-aware complaint operating system**. A **supervisor LLM** dynamically routes each complaint through specialist agents — classification, risk assessment, root cause analysis, resolution planning, compliance review, quality gate, and routing — deciding at each step which agent to invoke next based on the case state.

Specialists are equipped with **LangChain tools** for autonomous RAG retrieval (similar complaints, company policies, severity rubrics) via **PostgreSQL + pgvector**. Chat calls use the **OpenAI** or **DeepSeek** API. A built-in **web dashboard** provides real-time visibility into complaints, agent traces, and analytics.

## Agentic AI Architecture

```
                    ┌──────────┐
                    │  intake  │  (deterministic: PII redaction, validation)
                    └────┬─────┘
                         ▼
               ┌─────────────────┐
          ┌───►│   supervisor    │◄───┐
          │    │  (LLM decides)  │    │
          │    └──┬──┬──┬──┬──┬─┘     │
          │       │  │  │  │  │       │
     ┌────┘  ┌────┘  │  │  │  └───┐   └───┐
     ▼       ▼       ▼  ▼  ▼      ▼       ▼
 classify  risk  root_cause resolve compliance review  route→END
     │       │       │  │  │      │       │
     └───────┴───────┴──┴──┴──────┴───────┘
              (all return to supervisor)
```

**Key design decisions:**
- **Hub-and-spoke**: The supervisor uses `Command(goto=...)` for dynamic routing — no hardcoded conditional edges
- **Tool-equipped agents**: Specialists autonomously decide when to search similar complaints, look up policies, etc.
- **Safety limits**: Max 15 steps per workflow, max 3 invocations per agent, fallback routing on LLM parse failures
- **Observability**: Every node wrapped with OpenTelemetry spans, structured workflow events, and audit DB rows
- **PII redaction**: Applied at both ingestion time (historical data) and runtime intake (incoming complaints)

## Backend Architecture and Control Flow

The UI is server-rendered. FastAPI route handlers query SQLAlchemy models,
prepare plain context objects, and render Jinja templates.

```text
┌──────────────────────────── Browser (User) ─────────────────────────────┐
│                                                                         │
│  GET /                     GET /complaints/{id}      GET /trace/{id}    │
│   │                               │                        │            │
└───┼───────────────────────────────┼────────────────────────┼────────────┘
    │                               │                        │
    ▼                               ▼                        ▼
┌────────────────────────────── FastAPI App ───────────────────────────────┐
│ main.py                                                                  │
│  - include_router(app.ui.routes)                                         │
│  - include_router(app.api.routes)                                        │
│  - mount /static                                                         │
└───────────────┬───────────────────────────────────────────────┬──────────┘
                │                                               │
                ▼                                               ▼
    ┌──────────────────────┐                        ┌──────────────────────┐
    │ UI routes            │                        │ API routes           │
    │ app/ui/routes.py     │                        │ app/api/routes.py    │
    │                      │                        │                      │
    │ - dashboard()        │                        │ - create_complaint() │
    │ - complaint_detail() │                        │ - get/list complaints│
    │ - supervisor_trace() │                        │                      │
    └──────────┬───────────┘                        └──────────┬───────────┘
               │                                               │
               │ uses                                          │ uses
               ▼                                               ▼
    ┌───────────────────────────────┐               ┌───────────────────────────────┐
    │ SQLAlchemy Session + Models   │               │ Agentic Workflow (LangGraph)  │
    │ app/db/session.py             │               │ app/orchestrator/workflow.py  │
    │ app/db/models.py              │               │ + specialist agents/tools     │
    └──────────┬────────────────────┘               └──────────┬────────────────────┘
               │                                               │
               ▼                                               ▼
    ┌───────────────────────────────┐               ┌────────────────────────────────┐
    │ PostgreSQL (+pgvector)        │               │ Persist outputs / traces       │
    │ complaint_cases, workflow_*   │◄──────────────│ complaint_cases, workflow_runs │
    └───────────────────────────────┘               │ workflow_steps, etc.           │
                                                    └────────────────────────────────┘

        UI Render Path (server-side HTML)
        ----------------------------------
        UI route -> build context dict ->
        templates.TemplateResponse(request, "*.html", context={...})
                  │
                  ▼
           app/templates/base.html + page template
                  │
                  ▼
            HTML response (+ /static/css, /static/js)
```

**Key relationships**

- FastAPI handles routing and request lifecycle.
- SQLAlchemy handles DB reads/writes used by both UI pages and API workflows.
- Jinja templates render server-side HTML using route-provided context.
- The same DB tables power both API responses and dashboard/trace pages.
- Static assets in `app/static` provide theme and UI behavior on top of rendered HTML.

## Prerequisites

- **Python 3.11+** (3.11 recommended)
- **Docker** (optional but recommended) for PostgreSQL with pgvector
- **LLM API key** — either `OPENAI_API_KEY` or `DEEPSEEK_API_KEY` depending on provider
- For **local embeddings** (default): network access on first run to download the Hugging Face model, or set `EMBEDDING_PROVIDER=openai`

## Quick start

### 1. Clone or copy the project

```bash
git clone https://github.com/ayman-tech/Multi-Agent-Complaint-System.git
cd Multi-Agent-Complaint-System
```

### 2. Install dependencies

**Option A — uv (recommended):**

```bash
uv sync
```

**Option B — pip:**

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> If using **uv**, use `uv run` instead of `python` for all of below commands (e.g. `uv run app/retrieval/ingest`).

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at least:

- `LLM_PROVIDER` — `openai` (default) or `deepseek`
- `OPENAI_API_KEY` — required when `LLM_PROVIDER=openai`
- `DEEPSEEK_API_KEY` — required when `LLM_PROVIDER=deepseek`
- `DATABASE_URL` — leave default if you use the bundled Docker Compose Postgres

Optional:

- `OPENAI_CHAT_MODEL` / `DEEPSEEK_CHAT_MODEL` — override the default model
- `EMBEDDING_PROVIDER=huggingface` (default) or `openai`
- `HF_DEVICE=cpu` / `cuda` / `mps` — for local embedding model
- `JIRA_BASE_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` — enable Jira ticket creation via Jira MCP
- `JIRA_ISSUE_TYPE`, `JIRA_ISSUE_PRIORITY` — optional Jira defaults
- `LOG_LEVEL`, `SQL_ECHO`

### 4. Start PostgreSQL (pgvector)

```bash
docker compose up db -d
```
for **deployment on server** you have to starts both db + app in detached mode so do below :
```bash
sudo docker-compose up --build -d
```


Wait until the database is healthy (`docker compose ps`). Default connection:

`postgresql+psycopg2://postgres:postgres@localhost:5432/complaints`

### 5. (Optional) Load the CFPB complaint CSV into the vector tables

RAG quality improves if you ingest historical complaints. The ingester expects a CFPB-style CSV with columns like `Consumer complaint narrative`, `Product`, `Issue`, etc.

1. Download the [CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/) CSV.
2. Save it as **`complaints.csv`** in the project root, or pass a path with `--csv`.

```bash
# Stratified sample of 50k rows (good default; ~10+ minutes)
python -m app.retrieval.ingest --sample 50000

# Small dev run
python -m app.retrieval.ingest --sample 5000
```

PII redaction is applied automatically during ingestion — narratives are scrubbed for SSNs, card numbers, emails, and phone numbers before being stored in the vector DB.

**Important:** Choose `EMBEDDING_PROVIDER` **before** creating tables and ingesting. The `vector` columns are sized from the active embedding model; switching provider after data exists requires a fresh database.

### 6. Run the server

```bash
python uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

On startup, the app ensures the **pgvector** extension exists and creates tables if needed.

### 7. Use the dashboard

Open [http://localhost:8000](http://localhost:8000) to access the web dashboard:

| Screen | URL | Description |
|--------|-----|-------------|
| **Dashboard** | `/` | Paginated complaint table with KPIs, status badges, risk indicators |
| **Detail** | `/complaints/{id}` | Full case view — narrative, classification, risk, resolution, compliance, routing |
| **Trace** | `/trace/{run_id}` | Supervisor execution flow with step-by-step latency waterfall |
| **Analytics** | `/analytics` | Complaint volume charts, risk distribution, team workload |
| **Settings** | `/settings` | Company taxonomy, severity rubrics, routing rules (read-only) |

### 8. Submit a complaint (API)

```bash
curl -s -X POST "http://localhost:8000/api/v1/complaints" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "mock_bank",
    "consumer_narrative": "I was charged twice for the same credit card payment and the bank will not reverse the duplicate fee.",
    "product": "Credit card",
    "company": "Example Bank",
    "state": "CA",
    "channel": "web",
    "external_product_category": "credit_card",
    "external_issue_type": "billing_disputes",
    "requested_resolution": "Refund the duplicate fee"
  }' | python3 -m json.tool
```

**API endpoints:**

- `POST /api/v1/complaints` — submit and process a complaint
- `GET /api/v1/complaints` — list recent cases
- `GET /api/v1/complaints/{case_id}` — fetch one case
- `GET /api/v1/health` — health check
- `GET /docs` — interactive API docs (Swagger)

## Project layout

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app, static file mount, lifespan (logging + DB init) |
| `pyproject.toml` | Project metadata and dependencies (uv / pip) |
| **Agents** | |
| `app/agents/supervisor.py` | Supervisor agent — decides which specialist to invoke next |
| `app/agents/tools.py` | LangChain `@tool` definitions wrapping retrieval and knowledge services |
| `app/agents/tool_loop.py` | Reusable ReAct-style tool-calling loop for specialists |
| `app/agents/llm_factory.py` | LLM provider factory (OpenAI / DeepSeek) |
| `app/agents/classification.py` | Classification specialist (product category, issue type) |
| `app/agents/risk.py` | Risk assessment specialist (risk level, regulatory risk) |
| `app/agents/root_cause.py` | Root cause hypothesis specialist |
| `app/agents/resolution.py` | Resolution planning specialist |
| `app/agents/compliance.py` | Compliance check specialist |
| `app/agents/review.py` | Quality review specialist (approve / revise / escalate) |
| `app/agents/routing.py` | Rule-based routing to internal teams |
| `app/agents/intake.py` | Deterministic intake (PII redaction, validation) |
| **Orchestration** | |
| `app/orchestrator/workflow.py` | LangGraph hub-and-spoke agentic workflow |
| `app/orchestrator/state.py` | WorkflowState TypedDict with supervisor fields |
| `app/prompts/supervisor.md` | Supervisor system prompt |
| **Knowledge & Retrieval** | |
| `app/knowledge/` | Company knowledge layer (taxonomy, policy, routing, severity, controls) |
| `app/retrieval/` | Embeddings, pgvector indexes, CSV ingest with PII redaction |
| **Web UI** | |
| `app/ui/routes.py` | HTML view routes (dashboard, detail, trace, analytics, settings) |
| `app/ui/context.py` | DB query helpers for templates |
| `app/templates/` | Jinja2 templates (Tailwind CSS, dark theme) |
| `app/static/` | CSS and JS assets |
| **Infrastructure** | |
| `app/api/routes.py` | REST API endpoints |
| `app/db/` | SQLAlchemy models and session |
| `app/schemas/` | Pydantic request/response models |
| `app/observability/` | OTel tracing, structured events, audit persistence |
| `app/utils/pii.py` | Shared PII redaction utilities |
| `docker-compose.yml` | Local Postgres + pgvector |

## Batch testing

`testing_sample.py` loads a random sample of 5 complaints from a CSV and runs them through the full pipeline:

```bash
python testing_sample.py
```

Configure via environment variables: `TEST_CSV_PATH`, `TEST_SAMPLE_COUNT`, `COMPANY_ID`.

## Evaluations (optional)

`app/evals/run_evals.py` scores classification against labelled data. Place CSV or JSONL files under `app/evals/datasets/` with fields like `narrative`, `expected_product_category`, and `expected_issue_type`, then:

```bash
python -m app.evals.run_evals
```

## Troubleshooting

- **Database connection errors** — Ensure Docker Compose is up and `DATABASE_URL` matches credentials.
- **`CREATE EXTENSION vector` fails** — Use an image with pgvector (this repo uses `pgvector/pgvector:pg16`).
- **LLM API errors** — Confirm your API key (`OPENAI_API_KEY` or `DEEPSEEK_API_KEY`) and billing/quotas.
- **Embedding dimension mismatch** — Drop and recreate the database after changing `EMBEDDING_PROVIDER` so dimensions stay consistent.
- **Slow first request** — With Hugging Face embeddings, the model loads on the first pipeline run that needs retrieval.
- **Supervisor loops** — The supervisor has a 15-step max and 3-invocation-per-agent limit. If it hits these, it forces routing and finishes.

## License

Use and compliance responsibilities for third-party data (e.g. CFPB exports) and for production deployment of AI systems are yours; verify applicable terms and regulations.
