# Repository Architecture - Complaint Classification Agent

Generated: 2026-04-03

## 1. What this repository does

This project is a Python service that processes consumer complaints end-to-end using a LangGraph workflow. The pipeline:

1. Accepts a complaint via an HTTP API (FastAPI).
2. Normalizes/redacts the narrative (intake step).
3. Performs RAG-assisted classification (product category + issue type).
4. Performs RAG-assisted risk assessment.
5. Proposes a resolution recommendation using RAG over historical outcomes.
6. Runs a compliance check (regulatory/policy flags).
7. Performs a final quality-review gate (approve / revise / escalate).
8. Routes the case to a destination team based on classification, risk, and review decision.

Historical retrieval uses PostgreSQL + pgvector. LLM calls use the OpenAI API (agents are implemented with LangChain primitives).

## 2. High-level architecture (modules / layers)

The codebase is organized into a few clear layers:

### API layer

- `main.py`: FastAPI app creation and startup lifecycle.
- `app/api/routes.py`: HTTP routes for creating and reading complaint cases.

### Orchestration layer

- `app/orchestrator/workflow.py`: LangGraph state machine wiring nodes + conditional edges.
- `app/orchestrator/state.py`: shared `WorkflowState` type for nodes.
- `app/orchestrator/rules.py`: business rules for conditional routing/looping.

### Agent layer

Each agent is a small function that:
1. Builds an LLM prompt (system + human template).
2. Optionally retrieves similar precedent documents from pgvector.
3. Invokes the LLM and parses JSON into a Pydantic schema.

- `app/agents/intake.py`: validate/normalize/redact narrative and set initial status.
- `app/agents/classification.py`: RAG-assisted product/issue classification.
- `app/agents/risk.py`: RAG-assisted risk scoring and regulatory risk flags.
- `app/agents/resolution.py`: RAG-assisted resolution recommendation.
- `app/agents/compliance.py`: compliance officer check, returns flags/passed/notes.
- `app/agents/review.py`: QA gate producing approve/revise/escalate.
- `app/agents/routing.py`: mapping logic to select a destination team.

Prompts used by the LLM are stored as Markdown:

- `app/prompts/classification.md`
- `app/prompts/risk.md`
- `app/prompts/resolution.md`

### Retrieval + ingestion layer (RAG)

This layer provides:

- Embedding model selection (`app/retrieval/embeddings.py`).
- Vector index wrappers (`app/retrieval/complaint_index.py` and `app/retrieval/resolution_index.py`).
- A bulk ingestion script to populate vector tables from a CFPB-style CSV (`app/retrieval/ingest.py`).

### Persistence layer (PostgreSQL + SQLAlchemy)

- `app/db/session.py`: `init_db()` bootstraps pgvector extension and creates tables; `get_db()` yields a session.
- `app/db/models.py`: SQLAlchemy ORM models for:
  - `ComplaintCase` (application-level case record)
  - `ClassificationRecord`, `RiskRecord`, `ResolutionRecord`
  - `ComplaintEmbedding`, `ResolutionEmbedding` (pgvector-backed storage)

### Schemas (Pydantic)

Pydantic models define request/response payloads and agent outputs:

- `app/schemas/case.py`: API case payloads and status enum
- `app/schemas/classification.py`: `ClassificationResult`
- `app/schemas/risk.py`: `RiskAssessment`
- `app/schemas/resolution.py`: `ResolutionRecommendation`

### Observability

- `app/observability/logging.py`: structured JSON logging configuration.

### Optional evaluations

- `app/evals/run_evals.py`: basic evaluation harness for classification accuracy using a labeled dataset.

## 3. Runtime request flow (end-to-end)

### 3.1 API entry

`main.py` creates the FastAPI app. During the lifespan startup it:

- configures logging (`setup_logging()`)
- initializes DB schema (`init_db()`)

`app/api/routes.py` exposes:

- `POST /api/v1/complaints`
  - Receives a `CaseCreate` payload.
  - Calls `process_complaint(payload_dict)` from `app/orchestrator/workflow.py`.
  - Returns the final enriched `CaseRead` to the client.
  - Persists the base `ComplaintCase` row.

### 3.2 LangGraph workflow orchestration

`app/orchestrator/workflow.py` defines a LangGraph `StateGraph(WorkflowState)` and compiles it into `workflow`.

Nodes and their order:

- `intake` -> `classify` -> (conditional) -> `risk` -> `resolution` -> (conditional) -> `compliance` -> `review` -> (conditional) -> `route` -> END

Conditional edges are driven by helper functions in `app/orchestrator/rules.py`:

1. After classification:
   - `low_confidence_gate(state)`:
     - If `classification.confidence < 0.6` and `retry_count < MAX_RETRIES`, route to `reclassify` (loop back to `classify`).
     - Otherwise continue to `risk`.

2. After resolution:
   - `_compliance_router(state)`:
     - `needs_compliance_review(state)` decides if the case should pass through compliance.
     - High/critical risk or regulatory exposure => go to `compliance`.
     - Otherwise go straight to `review`.

3. After review:
   - `review_decision_router(state)`:
     - If decision is `revise` and `retry_count < MAX_RETRIES` => loop to `resolution`.
     - If decision is `escalate` => go to routing (routing interprets escalation through the review decision).
     - Otherwise => go to routing (`approve`).

### 3.3 Data passing via shared state

`app/orchestrator/state.py` defines `WorkflowState` as a `TypedDict` with keys like:

- `raw_payload`: original API payload dict
- `case`: `CaseRead` object (enriched as nodes run)
- `classification`: `ClassificationResult`
- `risk_assessment`: `RiskAssessment`
- `resolution`: `ResolutionRecommendation`
- `compliance`: dict of compliance flags
- `review`: dict of review decision/notes
- `routed_to`: routing output

Each node updates the `case` object in state and returns `{**state, <new_fields>}`.

## 4. Agent responsibilities (what each node does)

### 4.1 Intake agent (`run_intake`)

Location: `app/agents/intake.py`

- Normalizes narrative:
  - lowercases/collapses whitespace
  - applies lightweight redaction for patterns that look like SSNs and credit card-like numbers
- Stamps `submitted_at` if missing
- Sets `case.status = intake_complete`

### 4.2 Classification agent (`run_classification`) - RAG-assisted

Location: `app/agents/classification.py`

- Loads the system prompt from `app/prompts/classification.md`.
- Optionally uses `ComplaintIndex` to retrieve top-k similar complaint documents from pgvector.
- Builds a user message that includes:
  - the narrative
  - optional metadata (product/sub_product/company/state)
  - retrieved precedent context (if available)
- Invokes `ChatOpenAI` with a JSON-only output instruction (the prompt requires JSON).
- Parses the LLM output with `json.loads` into `ClassificationResult`.

### 4.3 Risk assessment agent (`run_risk_assessment`) - RAG-assisted

Location: `app/agents/risk.py`

- Loads `app/prompts/risk.md`.
- Optionally retrieves similar complaint context from `ComplaintIndex`.
- Provides classification JSON inside the prompt to ground the risk reasoning.
- Invokes LLM and parses into `RiskAssessment`.

### 4.4 Resolution agent (`run_resolution`) - RAG-assisted

Location: `app/agents/resolution.py`

- Loads `app/prompts/resolution.md`.
- Optionally retrieves similar resolutions from `ResolutionIndex` (based on the narrative).
- Includes narrative + classification + risk assessment in the prompt.
- Invokes LLM and parses into `ResolutionRecommendation`.

### 4.5 Compliance agent (`run_compliance_check`)

Location: `app/agents/compliance.py`

- Uses a dedicated compliance officer system prompt listing multiple statutes.
- Invokes LLM with narrative + classification + risk + proposed resolution.
- Parses and returns:
  - `flags`: list of issues
  - `passed`: boolean
  - `notes`: optional string

### 4.6 Review/QC agent (`run_review`)

Location: `app/agents/review.py`

- Runs final quality assurance against the full case dossier.
- Sends JSON strings for classification/risk/resolution and compliance to the LLM.
- Produces a structured decision:
  - `approve`: proceed to routing
  - `revise`: loop back to resolution
  - `escalate`: route as escalation

### 4.7 Routing agent (`run_routing`)

Location: `app/agents/routing.py`

- Routing logic is a mix of:
  - review decision: `escalate` => management escalation team
  - risk level: critical => executive complaints team
  - otherwise map product category to a team via `_PRODUCT_TO_TEAM`

## 5. Retrieval (pgvector) internals

### 5.1 Embedding model selection

Location: `app/retrieval/embeddings.py`

- `EMBEDDING_PROVIDER` env var controls whether embeddings come from:
  - local HuggingFace sentence-transformers
  - or OpenAI embeddings
- `get_embedding_dim()` returns the configured embedding dimension.
- The DB vector column dimensions are derived from this function in `app/db/models.py`.

Important operational constraint:

If you change the embedding model/provider, you must recreate the vector tables (or migrate), otherwise the vector dimensions will mismatch.

### 5.2 Vector index wrappers

Complaint similarity:

- `app/retrieval/complaint_index.py`
- `ComplaintIndex.search(query, k, product_filter, company_filter)`:
  - embeds the query
  - performs pgvector cosine-distance search
  - returns `Document` objects where `page_content` is the stored complaint text and `metadata` carries IDs and metadata

Resolution similarity:

- `app/retrieval/resolution_index.py`
- Similar approach, but uses `ResolutionEmbedding` rows and filters on product/outcome when provided.

### 5.3 Ingestion pipeline

Location: `app/retrieval/ingest.py`

This script:

- reads a CFPB-style CSV (default path: `complaints 2.csv` in the repo root)
- builds LangChain `Document` objects with:
  - `page_content`: narrative text and/or resolution text
  - `metadata`: product/issue/company/state plus IDs
- embeds the documents in batches and inserts them into two pgvector-backed tables:
  - `complaint_embeddings`
  - `resolution_embeddings`

Sampling strategy:

- Supports `--sample N` stratified sampling across `(Product, Issue)` strata.
- Ensures at least 1 doc per stratum so rare complaint types are not eliminated.

### 5.4 Index/query performance notes

The ORM models define HNSW indexes with cosine distance ops for the vector columns:

- `ix_complaint_embeddings_hnsw`
- `ix_resolution_embeddings_hnsw`

This makes retrieval approximate-nearest-neighbor and fast for large datasets.

## 6. Persistence and database schema

Location: `app/db/models.py` + `app/db/session.py`

### 6.1 Application tables

The database includes:

- `complaint_cases`
  - Stores the base input fields and current `status`.
- `classifications`
  - Stores structured classification results keyed by `case_id`.
- `risk_assessments`
  - Stores structured risk results keyed by `case_id`.
- `resolutions`
  - Stores resolution recommendations keyed by `case_id`.

### 6.2 Vector embedding tables

- `complaint_embeddings`
  - `embedding` is a pgvector column
  - `content` is the stored text passed to the LLM as RAG context
  - metadata columns exist for pre-filtering
- `resolution_embeddings`
  - analogous design, but `content` includes resolution outcomes and filtering can use `resolution_outcome`

### 6.3 Bootstrap

`init_db()` (called on startup) does:

1. `CREATE EXTENSION IF NOT EXISTS vector` (ensures pgvector)
2. `Base.metadata.create_all(...)` (creates ORM tables if missing)

## 7. Observability and logging

`app/observability/logging.py` configures:

- root logger with JSON log lines
- timestamp in UTC ISO format
- logs exception stack traces when available

It also suppresses overly verbose third-party logs (httpx/httpcore/openai/urllib3).

## 8. Evaluation harness

Location: `app/evals/run_evals.py`

The evaluation runner:

- loads labeled datasets from `app/evals/datasets/`
- calls `run_classification()` for each example
- computes simple metrics:
  - accuracy on product category
  - accuracy on issue type
  - average confidence

This is intended as a lightweight correctness check rather than a full offline benchmark.

## 9. Local development / deployment configuration

### Docker Compose

`docker-compose.yml` runs:

- a Postgres database with pgvector enabled via the `pgvector/pgvector:pg16` image
- database name: `complaints`
- port mapping: `5432:5432`

### Environment variables

`/.env.example` (template) indicates:

- `OPENAI_API_KEY`: required for the chat agents
- `DATABASE_URL`: points to the Postgres + pgvector instance
- `EMBEDDING_PROVIDER`: `huggingface` (default) or `openai`

Operational note:

The repository should not commit real API keys. Treat `OPENAI_API_KEY` as secret.

### Typical run sequence

1. Start Postgres: `docker compose up -d`
2. Ingest historical complaints (optional but recommended):
   - `python -m app.retrieval.ingest --sample 50000`
3. Start the API:
   - `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

## 10. Code/data artifacts in the repo

- `complaints.csv` (full dataset, used for experiments/ingestion)
- `complaint_data/split_file_0.csv`, etc.
  - created by `file_chunker.py` to split large CSVs into manageable chunks
- `cfpb_cr-annual-report_2023-03.pdf`
  - an extra artifact likely used for reference, not part of the runtime code
- `complaint_database.py` is present but empty (0 bytes)

## 11. Architecture caveats / consistency checks (important)

Because this request is “explain the entire repository”, it is useful to call out two consistency gaps visible in the current code:

1. Retry counters may not increment.
   - `WorkflowState` includes `retry_count`, and `rules.py` uses it to decide whether loops should continue.
   - However, `workflow.py` initializes `retry_count=0` and the node functions shown do not update it, so conditional gates relying on retry count may effectively loop without increasing the counter (or never allowing the “give up” path).

2. Persistence vs. enrichment mismatch.
   - The API route persists only the base `ComplaintCase` row (status and base fields).
   - The DB models also define `ClassificationRecord`, `RiskRecord`, and `ResolutionRecord`, but the shown persistence code does not insert those related records.
   - As a result, an enriched `CaseRead` returned by the workflow may not be fully persisted for later retrieval.

If you want, I can update the repository to address these (increment retries per loop, and persist agent outputs into the dedicated tables), but that is outside the scope of “write an explanation PDF”.

## 12. Summary

This repository implements a modular, RAG-assisted complaint-processing pipeline:

- FastAPI provides a simple request interface.
- LangGraph orchestrates a sequence of specialized LLM agents connected by conditional routing/looping rules.
- PostgreSQL + pgvector stores historical complaints and resolution precedents to ground classification, risk, and resolution suggestions.
- SQLAlchemy ORM models define both application tables and vector embedding tables.
- Prompts and output schemas enforce structured JSON exchanges across the system.

