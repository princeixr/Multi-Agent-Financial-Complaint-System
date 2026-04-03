# AI agent for complaint classification

FastAPI service that runs a **LangGraph** workflow over consumer complaints as a **company-aware complaint operating system**. The pipeline includes intake, a runtime **company knowledge layer** (taxonomy/severity/policy/routing/control candidates), classification mapping/validation, risk scoring, root-cause inference, resolution planning, compliance review, quality gate, and routing. Vector retrieval uses **PostgreSQL + pgvector**; chat calls use the **OpenAI** API.

## Prerequisites

- **Python 3.11+** (3.11 recommended)
- **Docker** (optional but recommended) for PostgreSQL with pgvector
- **OpenAI API key** (`OPENAI_API_KEY`) — used by all LLM agents (default model in code: `gpt-4o`)
- For **local embeddings** (default): network access on first run to download the Hugging Face model, or set `EMBEDDING_PROVIDER=openai` and use OpenAI embeddings (see below)

## Quick start

### 1. Clone or copy the project

```bash
cd "/path/to/AI Agent for Complaint Classification"
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at least:

- `OPENAI_API_KEY` — required for the pipeline to call the LLM.
- `DATABASE_URL` — leave default if you use the bundled Docker Compose Postgres.

Optional:

- `EMBEDDING_PROVIDER=huggingface` (default) or `openai`
- `HF_DEVICE=cpu` / `cuda` / `mps` — for local embedding model
- `LOG_LEVEL`, `SQL_ECHO`

Environment variables are loaded automatically from `.env` when the database layer is imported (API, ingest, and so on).

### 4. Start PostgreSQL (pgvector)

From the project root:

```bash
docker compose up -d
```

Wait until the database is healthy (`docker compose ps`). Default connection:

`postgresql+psycopg2://postgres:postgres@localhost:5432/complaints`

### 5. (Optional) Load the CFPB complaint CSV into the vector tables

RAG quality improves if you ingest a sample of historical complaints. The ingester expects a CFPB-style export whose columns match those in `app/retrieval/ingest.py` (for example `Consumer complaint narrative`, `Product`, `Issue`, etc.).

1. Download the public Consumer Financial Protection Bureau complaints dataset (CSV) from [Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/).
2. Save or symlink it as **`complaints 2.csv`** in the **project root** (same folder as `main.py`), or pass a path with `--csv`.

Then run (from project root, with venv activated):

```bash
# Stratified sample of 50k rows (good default; ~10+ minutes depending on CPU)
python -m app.retrieval.ingest --sample 50000

# Small dry run
python -m app.retrieval.ingest --sample 5000

# Use OpenAI embeddings instead of local (paid; dimension 1536 — DB must match)
EMBEDDING_PROVIDER=openai python -m app.retrieval.ingest --sample 50000
```

**Important:** Choose `EMBEDDING_PROVIDER` and embedding model **before** you create tables and ingest. The `vector` columns are sized from the active embedding model; switching provider after data exists requires a fresh database or migration.

On first use with `EMBEDDING_PROVIDER=huggingface`, the **sentence-transformers** model (default `BAAI/bge-small-en-v1.5`) is downloaded from Hugging Face.

### 6. Run the API

From the project root:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

On startup, the app ensures the **pgvector** extension exists and creates SQLAlchemy tables if needed.

- **Interactive docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health:** `GET http://localhost:8000/api/v1/health`

### 7. Submit a complaint (example)

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

Other routes:

- `GET /api/v1/complaints` — list recent cases
- `GET /api/v1/complaints/{case_id}` — fetch one case

## Project layout

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app and lifespan (logging + DB init) |
| `app/api/routes.py` | HTTP routes |
| `app/orchestrator/workflow.py` | LangGraph pipeline |
| `app/agents/` | LLM agents (intake, classification, risk, **root_cause**, resolution, compliance, review, routing) |
| `app/knowledge/` | Company knowledge layer (taxonomy/policy/routing/severity/control candidates) |
| `app/prompts/` | Markdown prompts for agents |
| `app/retrieval/` | Embeddings, pgvector indexes, CSV ingest |
| `app/db/` | SQLAlchemy models and session |
| `app/schemas/` | Pydantic request/response models |
| `docker-compose.yml` | Local Postgres + pgvector |
| `requirements.txt` | Python dependencies |

Additional artifacts:
| Path | Purpose |
|------|---------|
| `testing.ipynb` | Single-row end-to-end smoke test using a row from `complaint_data/` |
| `repository_architecture_detailed.pdf` | Detailed architecture + function/dependency documentation |
| `repository_architecture.pdf` | Earlier architecture summary |

## Evaluations (optional)

`app/evals/run_evals.py` can score classification against labelled data. Place CSV or JSONL files under `app/evals/datasets/` with fields such as `narrative`, `expected_product_category`, and `expected_issue_type`, then run:

```bash
python -m app.evals.run_evals
```

(Adjust the script if your dataset filenames differ.)

## Smoke test (one-row, local)

The repo includes `testing.ipynb`, which:

1. Loads exactly one row from `complaint_data/split_file_0.csv`.
2. Builds a `CaseCreate` payload (including `company_id` and external label fields).
3. If `OPENAI_API_KEY` is set, runs the full `process_complaint()` pipeline and prints:
   - `classification`
   - `risk_assessment`
   - `root_cause_hypothesis`
   - `proposed_resolution`
   - `compliance_flags`

Run it from the project root with your preferred notebook runner (Cursor/Jupyter).

## Troubleshooting

- **Database connection errors** — Ensure Docker Compose is up and `DATABASE_URL` matches credentials and database name.
- **`CREATE EXTENSION vector` fails** — Use an image that includes pgvector (this repo uses `pgvector/pgvector:pg16`).
- **OpenAI errors** — Confirm `OPENAI_API_KEY` and billing/quotas; agents use the OpenAI chat API.
- **Embedding dimension mismatch** — Drop and recreate the database (or tables) after changing `EMBEDDING_PROVIDER` / model so dimensions stay consistent.
- **Slow first request** — With Hugging Face embeddings, the model loads on the first pipeline run that needs retrieval.
- **Notebook import errors** — `testing.ipynb` uses `pandas`. If your notebook kernel does not include it, install `pandas` in the same environment as the repo's `.venv`.

## License

Use and compliance responsibilities for third-party data (e.g. CFPB exports) and for production deployment of AI systems are yours; verify applicable terms and regulations.
