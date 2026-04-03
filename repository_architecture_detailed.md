# Detailed Repository Architecture - Complaint Handling Platform

Generated: 2026-04-03

## 0. Repository purpose (what you built)

This repository is a Python service that accepts a consumer complaint case via HTTP and processes it through a LangGraph-orchestrated, multi-agent pipeline. The pipeline transforms the incoming complaint into an *internally actionable, company-aware* operational decision:

- Intake: normalize/redact and stamp metadata.
- Company context retrieval: fetch a slice of company-specific operational knowledge (taxonomy candidates, severity rubric snippets, policy snippets, routing ownership candidates, and root-cause controls).
- Classification mapping/validation: map the complaint to an internal operational product category and issue type using retrieved taxonomy candidates.
- Risk assessment: score risk and regulatory exposure using retrieved severity rubric + policy candidates.
- Root-cause hypothesis: predict likely operational/control failure mode using retrieved control knowledge and an evidence trace.
- Resolution planning: propose a resolution grounded in retrieved precedent/resolution context and company policy/routing hints.
- Compliance check: flag policy/regulatory compliance concerns grounded in policy candidates.
- Review gate: QA governance decision (approve/revise/escalate).
- Routing: select a destination team/queue using company ownership candidates and review/risk decisions.
- Persistence: store the base case plus enriched agent outputs into PostgreSQL (SQLAlchemy ORM tables + JSON/text columns + pgvector tables for RAG).

## 1. Core runtime architecture (modules/layers)

### 1.1 HTTP entry points

- `main.py`
  - Creates the FastAPI app.
  - Defines the app lifespan that calls `setup_logging()` and `init_db()` once at startup.
- `app/api/routes.py`
  - Defines the `APIRouter` and HTTP endpoints.
  - Endpoint handlers call `process_complaint()` and persist/return results.

### 1.2 Orchestration (LangGraph)

- `app/orchestrator/workflow.py`
  - Builds the compiled LangGraph `workflow`.
  - Defines node functions for each step: intake, company context, classification, risk, root cause, resolution, compliance, review, routing.
  - Defines conditional routing loops via helper functions in `app/orchestrator/rules.py`.
- `app/orchestrator/state.py`
  - Defines `WorkflowState` typed dictionary (the shared object passed between nodes).
- `app/orchestrator/rules.py`
  - Contains business rules for conditional edges: low-confidence reclassification, whether to run compliance, and whether review requests revision/escalation.

### 1.3 Agents (LLM + structured JSON)

Each agent is implemented as a small function:

- Builds a prompt (system template + human input).
- Optionally retrieves precedent context from pgvector indices (complaints/resolutions).
- Calls OpenAI Chat via LangChain (`ChatOpenAI`).
- Parses JSON (`json.loads`) into a Pydantic schema object.

Agents in this repo:

- `app/agents/intake.py`
  - `_normalise_text()`
  - `run_intake()`
- `app/agents/classification.py`
  - `_load_prompt()`
  - `run_classification()`
- `app/agents/risk.py`
  - `_load_prompt()`
  - `run_risk_assessment()`
- `app/agents/root_cause.py`
  - `run_root_cause_hypothesis()`
- `app/agents/resolution.py`
  - `_load_prompt()`
  - `run_resolution()`
- `app/agents/compliance.py`
  - `run_compliance_check()`
- `app/agents/review.py`
  - `run_review()`
- `app/agents/routing.py`
  - `run_routing()`

### 1.4 Company knowledge layer (company reconfigurability boundary)

The architecture shift is that business logic is not fully hardcoded into prompts/edges. Instead, the orchestrator retrieves a company-specific knowledge slice at runtime.

- `app/knowledge/company_knowledge.py`
  - `_tokenize()`
  - `_score_by_cues()`
  - `CompanyContext` (dataclass)
  - `CompanyKnowledgeService.build_company_context()`
- `app/knowledge/mock_company_pack.py`
  - Demo data: operational taxonomy, severity rubric, policy snippets, routing matrix, and root-cause controls.

In this repo, the knowledge layer is *simulated* with keyword cue matching (so you can run end-to-end without ingesting a dedicated company pack into pgvector yet).

### 1.5 Retrieval + ingestion (pgvector)

RAG retrieval uses PostgreSQL + pgvector. This repo uses vector storage in two separate domains:

- Historical complaint narratives for classification/risk grounding:
  - `app/retrieval/complaint_index.py` + `app/retrieval/embeddings.py` + `app/db/models.py`
  - pgvector table: `complaint_embeddings`
- Historical complaint + resolution outcomes for resolution grounding:
  - `app/retrieval/resolution_index.py` + `app/retrieval/embeddings.py` + `app/db/models.py`
  - pgvector table: `resolution_embeddings`

Historical ingestion (CSV -> pgvector):

- `app/retrieval/ingest.py`
  - `_collect_stratified_sample()`
  - `_row_to_complaint_doc()`
  - `_row_to_resolution_doc()`
  - `ingest_csv()`

### 1.6 Persistence layer (SQLAlchemy + PostgreSQL)

- `app/db/models.py`
  - ORM tables:
    - `ComplaintCase`
    - `ClassificationRecord`
    - `RiskRecord`
    - `ResolutionRecord`
    - `ComplaintEmbedding` (pgvector)
    - `ResolutionEmbedding` (pgvector)
- `app/db/session.py`
  - `init_db()` (bootstraps pgvector extension, creates tables, and adds new columns if missing)
  - `get_db()` (context manager providing a transactional SQLAlchemy session)

### 1.7 Observability

- `app/observability/logging.py`
  - `JSONFormatter.format()`
  - `setup_logging()`

### 1.8 Offline / dev utilities

- `app/evals/run_evals.py`
  - `load_dataset()`
  - `evaluate_classification()`
- `file_chunker.py`
  - Script-only: splits `complaints.csv` into chunk CSVs inside `complaint_data/`
- `generate_repository_architecture_pdf.py`
  - `render_pdf_from_markdown()` (used for doc generation)

## 2. End-to-end request flow (with function call dependencies)

### 2.1 Application startup

Entry point:

- `main.py`
  - `lifespan(_app)`
    - calls `setup_logging()` from `app/observability/logging.py`
      - `setup_logging()` configures the root logger handlers to emit JSON lines using `JSONFormatter.format()`
    - calls `init_db()` from `app/db/session.py`
      - `init_db()`:
        - executes `CREATE EXTENSION IF NOT EXISTS vector`
        - ensures new columns exist on `complaint_cases` via `ALTER TABLE ... ADD COLUMN` for known demo upgrades
        - calls `Base.metadata.create_all()` to create ORM tables if missing
    - yields control to the running API server

Dependencies:

- `main.py.lifespan()` depends on:
  - `app.observability.logging.setup_logging()`
  - `app.db.session.init_db()`

### 2.2 POST `/api/v1/complaints` (create complaint)

HTTP handler:

- `app/api/routes.py.create_complaint(payload: CaseCreate) -> CaseRead`
  - depends on:
    - `process_complaint()` from `app/orchestrator/workflow.py`
    - DB session context manager `get_db()` from `app/db/session.py`
    - ORM classes `ComplaintCase`, `ClassificationRecord`, `RiskRecord`, `ResolutionRecord`

Detailed call chain:

1. `payload.model_dump()` produces a dict that includes `company_id` (if provided).
2. `process_complaint(payload_dict)` is called.
   - `app/orchestrator/workflow.py.process_complaint()`:
     - constructs `initial_state`:
       - `"raw_payload": payload`
       - `"retry_count": 0`
       - `"company_id": payload.get("company_id") or "mock_bank"`
     - calls `workflow.invoke(initial_state)`.
3. The LangGraph workflow runs node functions in order and conditionally.
4. The returned `final_state` includes `"case": CaseRead` populated by each node/agent.
5. Route persists:
   - Base enrichment fields on `ComplaintCase`:
     - `external_schema_json`
     - `operational_mapping_json`
     - `evidence_trace_json`
     - `severity_class`
     - `team_assignment`
     - `sla_class`
     - `root_cause_hypothesis_json`
     - `compliance_flags_json`
     - `review_notes`
     - `routed_to`
   - Agent outputs into dedicated relational tables:
     - `ClassificationRecord` from `case.classification`
     - `RiskRecord` from `case.risk_assessment`
     - `ResolutionRecord` from `case.proposed_resolution`
6. It returns the enriched in-memory `case` as the HTTP response.

Key helper dependencies inside `routes.py`:

- `_json_or_none(value)`:
  - used to serialize optional dict fields into JSON strings for DB columns.
- `_case_read_from_db(db_case)`:
  - used by GET endpoints to reconstruct a `CaseRead` by loading JSON strings back with `json.loads()`.

### 2.3 GET `/api/v1/complaints/{case_id}` and list

- `app/api/routes.py.get_complaint(case_id)`
  - calls `_case_read_from_db()` after loading `ComplaintCase` from DB via `get_db()`.
- `app/api/routes.py.list_complaints(limit, offset)`
  - loads recent rows and maps each ORM row to `CaseRead` using `_case_read_from_db()`.

Dependencies:

- `_case_read_from_db()`:
  - expects `ComplaintCase.classification`, `ComplaintCase.risk_assessment`, and `ComplaintCase.resolution` relationships to be loaded by SQLAlchemy.
  - builds dicts for `classification`, `risk_assessment`, and `proposed_resolution`.
  - converts JSON stored in:
    - `evidence_trace_json`
    - `external_schema_json`
    - `operational_mapping_json`
    - `root_cause_hypothesis_json`
    - `compliance_flags_json`
    using `json.loads()`.

## 3. LangGraph workflow (nodes, state, conditional edges)

### 3.1 Shared state object

- `app/orchestrator/state.py.WorkflowState` typed dict defines (total=False):
  - Inputs:
    - `raw_payload: dict`
    - `company_id: str`
  - Outputs by nodes:
    - `case: CaseRead`
    - `classification: ClassificationResult`
    - `operational_mapping: dict`
    - `evidence_trace: EvidenceTrace`
    - `risk_assessment: RiskAssessment`
    - `company_context: dict`
    - `resolution: ResolutionRecommendation`
    - `compliance: dict`
    - `review: dict`
    - `routed_to: str`
    - `root_cause_hypothesis: RootCauseHypothesis`
  - Meta:
    - `retry_count: int`
    - `error: Optional[str]`

Dependencies:

- Node functions use `state` keys as inputs/outputs and rely on schemas:
  - `CaseRead` from `app/schemas/case.py`
  - `ClassificationResult` from `app/schemas/classification.py`
  - `EvidenceTrace` from `app/schemas/evidence.py`
  - `RiskAssessment` from `app/schemas/risk.py`
  - `ResolutionRecommendation` from `app/schemas/resolution.py`
  - `RootCauseHypothesis` from `app/schemas/root_cause.py`

### 3.2 Conditional rules

- `app/orchestrator/rules.py` defines:
  - `MAX_RETRIES = 2`
  - `low_confidence_gate(state) -> str`
    - reads `state.get("classification")` and `state.get("retry_count", 0)`
    - returns:
      - `"reclassify"` if `classification.confidence < 0.6` and retry_count < MAX_RETRIES
      - otherwise `"continue"`
  - `needs_compliance_review(state) -> bool`
    - if `risk_assessment` missing: returns True (cautious default)
    - otherwise returns True when:
      - `risk.regulatory_risk == True`, OR
      - `risk.risk_level.value in ("high", "critical")`
  - `review_decision_router(state) -> str`
    - reads `state.get("review", {})["decision"]`
    - if `decision == "revise"` and retry_count < MAX_RETRIES: returns `"revise"`
    - if `decision == "escalate"`: returns `"escalate"`
    - else returns `"route"`

### 3.3 Node functions and their dependencies

Node functions are in `app/orchestrator/workflow.py`:

1. `intake_node(state) -> WorkflowState`
   - Depends on:
     - `CaseCreate(**state["raw_payload"])` to validate payload fields
     - `run_intake(payload)` from `app/agents/intake.py`
   - Output:
     - sets `"case": CaseRead`

2. `company_context_node(state) -> WorkflowState`
   - Depends on:
     - `CompanyKnowledgeService.build_company_context(case.consumer_narrative)`
     - `EvidenceTrace` and `EvidenceItem` schemas
   - Responsibilities:
     - builds a `company_context` dict:
       - `company_id`
       - `taxonomy_candidates`
       - `severity_candidates`
       - `policy_candidates`
       - `routing_candidates`
       - `root_cause_controls`
     - creates an `EvidenceTrace` containing evidence items pointing at company knowledge slices
     - stores `evidence_trace` into both:
       - `state["evidence_trace"]`
       - and `case.evidence_trace`

3. `classify_node(state) -> WorkflowState`
   - Depends on:
     - `run_classification(...)` from `app/agents/classification.py`
     - `_complaint_index_singleton()` which instantiates `ComplaintIndex()` (lazy singleton)
   - Special retry behavior:
     - if `state.get("classification") is not None`, increments `state["retry_count"]` before calling the classifier again.
   - Responsibilities:
     - sets `case.classification` (as dict) via `case.classification = result.model_dump()`
     - sets `case.status = CaseStatus.CLASSIFIED`
     - sets `case.operational_mapping` with normalized internal label mapping:
       - product_category
       - issue_type
       - sub_issue

4. `risk_node(state) -> WorkflowState`
   - Depends on:
     - `run_risk_assessment(...)` from `app/agents/risk.py`
     - complaint RAG: `_complaint_index_singleton()`
   - Responsibilities:
     - sets `case.risk_assessment = result.model_dump()`
     - sets `case.severity_class = result.risk_level.value`
     - sets `case.status = CaseStatus.RISK_ASSESSED`

5. `root_cause_node(state) -> WorkflowState`
   - Depends on:
     - `run_root_cause_hypothesis(...)` from `app/agents/root_cause.py`
     - `company_context["root_cause_controls"]`
     - `state["evidence_trace"]`
   - Responsibilities:
     - sets `case.root_cause_hypothesis = result.model_dump()`
     - stores `root_cause_hypothesis` in state as well
     - sets `case.status` currently to `CaseStatus.RISK_ASSESSED` (note: the enum has no separate root-cause status)

6. `resolution_node(state) -> WorkflowState`
   - Depends on:
     - `run_resolution(...)` from `app/agents/resolution.py`
     - `_resolution_index_singleton()` for similar resolution retrieval
     - passes `root_cause_hypothesis` and `company_context` into the agent
   - Retry behavior:
     - if `state.get("resolution") is not None`, increments `retry_count`.
   - Responsibilities:
     - sets `case.proposed_resolution = result.model_dump()`
     - sets `case.status = CaseStatus.RESOLUTION_PROPOSED`

7. `compliance_node(state) -> WorkflowState`
   - Depends on:
     - `run_compliance_check(...)` from `app/agents/compliance.py`
   - Responsibilities:
     - sets `case.compliance_flags = result.get("flags", [])`
     - updates `case.evidence_trace` to include the latest `evidence_trace` snapshot if present (currently it reuses the existing evidence trace)
     - sets `case.status = CaseStatus.COMPLIANCE_CHECKED`

8. `review_node(state) -> WorkflowState`
   - Depends on:
     - `run_review(...)` from `app/agents/review.py`
   - Responsibilities:
     - sends JSON strings of classification/risk/resolution/compliance into the review LLM
     - sets `case.review_notes = result.get("notes", "")`
     - sets `case.status = CaseStatus.REVIEWED`

9. `routing_node(state) -> WorkflowState`
   - Depends on:
     - `run_routing(...)` from `app/agents/routing.py`
   - Responsibilities:
     - sets `case.routed_to = destination`
     - sets `case.team_assignment = destination`
     - sets `case.status = CaseStatus.ROUTED`

### 3.4 Workflow graph edges

In `build_workflow()`:

- Entry point:
  - `intake` (then `company_context`, then `classify`)
- Conditional edges:
  - After `classify`:
    - `"continue"` -> `risk`
    - `"reclassify"` -> `classify`
  - After `resolution`:
    - `"compliance"` -> `compliance`
    - `"review"` -> `review`
  - After `review`:
    - `"route"` -> `route`
    - `"revise"` -> `resolution`
    - `"escalate"` -> `route`
- Terminal:
  - `route` -> `END`

## 4. Agent-by-agent detailed function map and dependencies

### 4.1 `app/agents/intake.py`

#### `_normalise_text(text: str) -> str`
Dependencies:

- Python `re` module only.
Transforms:
- Redacts SSN-like patterns and 16-digit card-like patterns.
- Collapses whitespace to single spaces and strips.

#### `run_intake(payload: CaseCreate) -> CaseRead`
Dependencies:

- `CaseCreate` and `CaseRead` and `CaseStatus` from `app/schemas/case.py`.
Calls:
- `_normalise_text(payload.consumer_narrative)`.
Side effects on output:
- Creates `CaseRead` object with:
  - `consumer_narrative` set to cleaned narrative
  - `product`, `sub_product`, `company`, `state`, `zip_code`, `channel`
  - `submitted_at` stamped if missing
  - `status = CaseStatus.INTAKE_COMPLETE`
- Sets `case.external_schema` with the optional external labels:
  - `external_product_category`
  - `external_issue_type`
  - `requested_resolution`

### 4.2 `app/agents/classification.py`

#### `_load_prompt() -> str`
Dependencies:
- Reads prompt from `app/prompts/classification.md` using `Path.read_text()`.

#### `run_classification(...) -> ClassificationResult`
Signature dependencies:

- Inputs:
  - narrative and optional `product`, `sub_product`, `company`, `state`.
  - `complaint_index: ComplaintIndex | None` for pgvector retrieval.
  - `company_context: dict | None` for company candidate labels.
  - `model_name` and `temperature`.
Calls:
- Optional retrieval:
  - `complaint_index.search(narrative, k=3)` to produce `similar_context`.
  - `similar_context` is stored as a string joined by `\n---\n`.
- Company fallback:
  - If `company_context` is None, it calls:
    - `CompanyKnowledgeService().build_company_context(narrative)` to produce a demo knowledge slice.
- Prompt construction:
  - uses LangChain `ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])`.
  - constructs `user_message` combining:
    - narrative + optional metadata
    - `similar_context` (if any)
    - taxonomy snippet derived from `company_context["taxonomy_candidates"]`.
- LLM invocation and parsing:
  - `llm = ChatOpenAI(model=model_name, temperature=temperature)`
  - `response = chain.invoke({"input": user_message})`
  - `result_data = json.loads(response.content)`
  - `result = ClassificationResult(**result_data)`

Output:

- Returns `ClassificationResult`, whose fields are:
  - `product_category` (Enum)
  - `issue_type` (Enum)
  - `sub_issue` (optional)
  - `confidence` (float 0..1)
  - `reasoning`
  - `keywords`

### 4.3 `app/agents/risk.py`

#### `_load_prompt() -> str`
Reads `app/prompts/risk.md`.

#### `run_risk_assessment(...) -> RiskAssessment`
Calls:
- Optional pgvector precedent:
  - `complaint_index.search(narrative, k=3)` to produce `similar_context`.
- Company knowledge injection:
  - If `company_context` is provided, it pulls:
    - `severity_candidates`
    - `policy_candidates`
  - Constructs `severity_snippet`.
- Prompt + LLM:
  - builds ChatPromptTemplate with system prompt and `{input}`
  - invokes `ChatOpenAI` and parses via `json.loads`
  - returns `RiskAssessment(**result_data)`

### 4.4 `app/agents/root_cause.py`

#### `run_root_cause_hypothesis(...) -> RootCauseHypothesis`
Dependencies:

- `ChatPromptTemplate` + `ChatOpenAI`
- Schemas:
  - `ClassificationResult`, `RiskAssessment`, `EvidenceTrace`, `RootCauseHypothesis`
Calls:
- It serializes `company_root_cause_controls` as JSON text (`json.dumps` per candidate).
- It serializes `evidence_trace` via `evidence_trace.model_dump_json()`.
- Builds user message with narrative + classification + risk + controls + evidence trace.
- Invokes LLM and parses JSON into `RootCauseHypothesis`.

### 4.5 `app/agents/resolution.py`

#### `_load_prompt() -> str`
Reads `app/prompts/resolution.md`.

#### `run_resolution(...) -> ResolutionRecommendation`
Calls:
- Optional pgvector retrieval:
  - `resolution_index.search(narrative, k=3)` -> `similar_resolutions`.
- Optional company injection:
  - `policy_candidates` and `routing_candidates` from `company_context`.
- Optional root-cause grounding:
  - if `root_cause_hypothesis` is provided, appends it to the user message.
- LLM:
  - `ChatPromptTemplate.from_messages([...])`
  - `ChatOpenAI(model=model_name, temperature=temperature)`
  - `json.loads(response.content)` into `ResolutionRecommendation`

### 4.6 `app/agents/compliance.py`

#### `run_compliance_check(...) -> dict`
Dependencies:

- `_SYSTEM_PROMPT` internal string that instructs compliance officer behavior.
- `ChatPromptTemplate` and `ChatOpenAI`.
Calls:
- If `company_context` exists, pulls `policy_candidates` and includes them in `user_message`.
- Sends:
  - narrative
  - classification JSON
  - risk JSON
  - proposed resolution JSON
  - policy snippet
- Parses `json.loads(response.content)` into a raw dict (not a Pydantic schema).

### 4.7 `app/agents/review.py`

#### `run_review(...) -> dict`
Dependencies:
- Internal `_SYSTEM_PROMPT` for governance logic.
- `ChatPromptTemplate` and `ChatOpenAI`.
Calls:
- Builds user message from:
  - narrative
  - classification_json
  - risk_json
  - resolution_json
  - compliance_json
- Invokes LLM and parses JSON:
  - `result = json.loads(response.content)`

### 4.8 `app/agents/routing.py`

#### `run_routing(case, classification, risk, root_cause_hypothesis, review_decision, company_context) -> str`
Dependencies:
- Uses `RiskLevel` and `ProductCategory` enums for compatibility.
- Uses `_PRODUCT_TO_TEAM` static mapping as fallback.
Calls:
- Extracts routing candidates from `company_context["routing_candidates"]` when available.
- Routing decision:
  - if `review_decision == "escalate"`: route to `management_escalation_team`
  - elif `risk.risk_level == RiskLevel.CRITICAL`: route to `executive_team`
  - else: map classification product_category to team using `team_by_product_category`
    - includes fallback logic if the mapping keys are enums rather than strings.

Note:

`root_cause_hypothesis` is currently accepted but not used to influence routing logic (routing uses only review decision + risk + product category + company routing matrix).

## 5. Company knowledge layer (detailed)

### 5.1 Mock pack constants (`app/knowledge/mock_company_pack.py`)

This file defines demo company knowledge structures:

- `MockCompanyPack.company_id`
- `OPERATIONAL_TAXONOMY`
  - `product_categories`: list of objects with fields:
    - product_category (string)
    - definition
    - cues: keyword list for matching
  - `issue_types`: list of issue type objects with cues
- `SEVERITY_RUBRIC`
  - list of severity objects with:
    - level
    - description
    - cues
    - escalation boolean
- `POLICY_SNIPPETS`
  - list of policy snippet objects
- `ROUTING_MATRIX`
  - `team_by_product_category` map
  - `executive_team`
  - `management_escalation_team`
- `ROOT_CAUSE_CONTROLS`
  - list of root cause control categories and:
    - cues
    - suggested controls_to_check

### 5.2 Keyword cue retrieval (`app/knowledge/company_knowledge.py`)

#### `_tokenize(text: str) -> set[str]`
- Lowercase and split on non-alphanumeric/underscore.

#### `_score_by_cues(narrative: str, cues: Iterable[str]) -> float`
- Tokenize the narrative and cue phrases.
- Computes a simple overlap score:
  - |token_overlap| / |cue_tokens|

#### `CompanyKnowledgeService.__init__(company_id: str | None = None)`
- Reads `COMPANY_ID` from environment if `company_id` not provided.
- Validates company_id against the demo pack id.

#### `CompanyKnowledgeService.build_company_context(narrative: str) -> CompanyContext`
Steps:
1. Takes product_categories and issue_types from the mock pack.
2. Scores each taxonomy candidate based on cue overlap using `_score_by_cues`.
3. Selects top candidates:
   - top 3 product candidates
   - top 5 issue candidates
   - top 3 severity candidates
   - top 3 policy snippets
   - top 3 root-cause control candidates
4. Returns:
   - `CompanyContext(company_id, taxonomy_candidates, severity_candidates, policy_candidates, routing_candidates, root_cause_controls)`

Dependencies:
- `build_company_context()` uses:
  - `self._pack` from `MockCompanyPack`
  - `_score_by_cues()` and `_tokenize()`.

## 6. Persistence and DB schema (detailed)

### 6.1 ORM models (`app/db/models.py`)

At import time, models compute:

- `EMBEDDING_DIM = get_embedding_dim()` from `app/retrieval/embeddings.py`.

This means:

- Changing the embedding model/provider can change the expected vector dimensions.
- The pgvector tables/columns must match that dimension, otherwise ingestion/retrieval can fail.

#### `ComplaintCase` table: `complaint_cases`

Core columns:
- `id` (uuid hex string)
- `status` (string)
- input fields:
  - `consumer_narrative`
  - `product`, `sub_product`, `company`, `state`, `zip_code`, `channel`
  - `submitted_at`, `created_at`, `updated_at`

Company-aware JSON/text columns:
- `external_schema_json`
- `operational_mapping_json`
- `evidence_trace_json`
- `severity_class`
- `team_assignment`
- `sla_class`
- `root_cause_hypothesis_json`
- `compliance_flags_json`
- `review_notes`
- `routed_to`

Relationships:
- `classification` relationship to `ClassificationRecord` (uselist=False)
- `risk_assessment` relationship to `RiskRecord` (uselist=False)
- `resolution` relationship to `ResolutionRecord` (uselist=False)

#### `ClassificationRecord` table: `classifications`
- `case_id` foreign key
- `product_category`, `issue_type`, `sub_issue`
- `confidence`, `reasoning`

#### `RiskRecord` table: `risk_assessments`
- `case_id`
- `risk_level`, `risk_score`, `regulatory_risk`
- `financial_impact_estimate`
- `escalation_required`, `reasoning`

#### `ResolutionRecord` table: `resolutions`
- `case_id`
- `recommended_action`, `description`
- `estimated_resolution_days`
- `monetary_amount`, `confidence`, `reasoning`

#### Vector tables (pgvector)

- `ComplaintEmbedding` table: `complaint_embeddings`
  - `content`: text stored for retrieval context
  - `embedding`: `Vector(EMBEDDING_DIM)`
  - metadata columns for optional pre-filtering:
    - product, issue, company, state, etc.
  - HNSW index `ix_complaint_embeddings_hnsw`
- `ResolutionEmbedding` table: `resolution_embeddings`
  - `content`, `embedding`
  - metadata columns:
    - product, issue, company, resolution_outcome
  - HNSW index `ix_resolution_embeddings_hnsw`

### 6.2 DB initialization and sessions (`app/db/session.py`)

#### `init_db() -> None`
Calls:
- `engine.connect()`
- Executes:
  - `CREATE EXTENSION IF NOT EXISTS vector`
  - Safe schema upgrades:
    - Checks `information_schema.columns` for `complaint_cases`
    - Adds any missing columns from a hardcoded list with `ALTER TABLE complaint_cases ADD COLUMN ...`
- Calls:
  - `Base.metadata.create_all(bind=engine)`

#### `get_db() -> Generator[Session, None, None]`
- Provides a SQLAlchemy session with:
  - commit on success
  - rollback on exception
  - close in finally block

Dependencies:
- `routes.py` depends on `get_db()`.
- `ComplaintIndex` and `ResolutionIndex` depend on `SessionLocal` directly (not on `get_db()`).

## 7. Retrieval and embedding system (detailed)

### 7.1 Embedding factory (`app/retrieval/embeddings.py`)

#### Globals
- `EMBEDDING_PROVIDER` (env var, default `huggingface`)
- `HF_MODEL_NAME`, `HF_DEVICE`
- `OPENAI_MODEL_NAME`
- `_MODEL_DIMENSIONS` mapping model name -> embedding dimension.

#### `get_embedding_dim() -> int`
- If `EMBEDDING_PROVIDER == "openai"` uses `OPENAI_MODEL_NAME`, else uses `HF_MODEL_NAME`.
- Looks up dimension in `_MODEL_DIMENSIONS`.
- Defaults to 384 if unknown.

#### `get_embeddings() -> Embeddings`
- If provider is openai:
  - returns `OpenAIEmbeddings(model=OPENAI_MODEL_NAME)`
- Else:
  - returns `HuggingFaceEmbeddings(model_name=HF_MODEL_NAME, model_kwargs={"device": HF_DEVICE}, encode_kwargs={"normalize_embeddings": True})`

### 7.2 pgvector index wrapper: complaints (`app/retrieval/complaint_index.py`)

Class: `ComplaintIndex`

#### `__init__()`
- Sets `self._embeddings = get_embeddings()`.

#### `add_complaints(docs: list[Document]) -> None`
Dependencies:
- `doc.page_content` -> embedding text
- `doc.metadata` keys -> `ComplaintEmbedding` columns
Calls:
- `vectors = self._embeddings.embed_documents(texts)`
- Uses `SessionLocal()`:
  - builds `ComplaintEmbedding(...)` rows
  - `session.bulk_save_objects(rows)`
  - commit or rollback

#### `search(query: str, k: int, product_filter: Optional[str], company_filter: Optional[str]) -> list[Document]`
Calls:
- `query_vec = self._embeddings.embed_query(query)`
- Builds SQLAlchemy statement:
  - selects `ComplaintEmbedding.content`, `complaint_id`, `product`, `issue`, `company`, `state`
  - uses `ComplaintEmbedding.embedding.cosine_distance(query_vec).label("distance")`
  - orders by `"distance"`, limits k
  - optionally adds `.where()` filters for product/company
- Executes and converts results to LangChain `Document(page_content=row.content, metadata=...)`.

#### `search_with_scores(...)`
- Wrapper around `search()` returning `(Document, distance)` tuples.

#### `count()`
- Executes raw SQL `SELECT COUNT(*) FROM complaint_embeddings`.

### 7.3 pgvector index wrapper: resolutions (`app/retrieval/resolution_index.py`)

Class: `ResolutionIndex`

Same overall structure as `ComplaintIndex` but uses:
- `ResolutionEmbedding` ORM model
- filters can include `product_filter` and `resolution_filter`
- metadata includes `resolution_outcome`

### 7.4 Ingestion pipeline (`app/retrieval/ingest.py`)

Primary entry:
- `ingest_csv(...) -> dict[str, int]`

Dependencies:
- DB: calls `init_db()`
- Indices:
  - `ComplaintIndex()` and `ResolutionIndex()`
- Data:
  - default CSV path: `complaints 2.csv` in repo root.

Steps:
1. Validate CSV existence.
2. Initialize DB (pgvector extension + tables).
3. Choose rows:
   - if `sample_size` is not None:
     - calls `_collect_stratified_sample(csv_path, sample_size, seed)`
   - else:
     - reads all rows with narrative length >= MIN_NARRATIVE_LENGTH.
4. For each row:
   - `_row_to_complaint_doc(row)`:
     - returns Document with narrative + metadata
   - `_row_to_resolution_doc(row)`:
     - returns Document with narrative + resolution text + metadata
5. Accumulate two batches and flush via:
   - `complaint_idx.add_complaints(complaint_batch)`
   - `resolution_idx.add_resolutions(resolution_batch)`
6. Returns stats:
   - `rows_sampled`
   - `complaint_docs`
   - `resolution_docs`

Sampling details:
- `_collect_stratified_sample()`:
  - first pass buckets rows by `(Product, Issue)`
  - allocates budget proportionally to each stratum with:
    - `min_per_stratum = 1`
  - samples within each stratum using seeded RNG
  - shuffles final sample to mix strata across batches

CLI:
- At the bottom of `ingest.py`, `if __name__ == "__main__":` parses:
  - `--csv`, `--sample`, `--no-sample`, `--batch-size`, `--seed`
  - calls `ingest_csv()` and prints a summary.

## 8. Observability (`app/observability/logging.py`)

### `JSONFormatter.format(record) -> str`
- Constructs a dict with:
  - timestamp (UTC ISO), level, logger name, message
  - module, function, line
  - exception stack trace when available
- Returns `json.dumps(log_entry)`.

### `setup_logging(level: str | None = None) -> None`
- Computes `log_level` from parameter or `LOG_LEVEL` env var.
- Configures the root logger:
  - clears any pre-existing handlers
  - uses `logging.StreamHandler(sys.stdout)` with JSONFormatter
- Suppresses noisy third-party loggers:
  - `httpcore`, `httpx`, `openai`, `urllib3`

## 9. Evaluation harness (`app/evals/run_evals.py`)

### `load_dataset(filename: str) -> list[dict[str, Any]]`
- Reads from `DATASETS_DIR = app/evals/datasets/`.
- Supports:
  - `.csv` using `csv.DictReader`
  - `.jsonl` / `.json` using line-by-line `json.loads`

### `evaluate_classification(dataset_file, model_name) -> dict[str, float]`
- Loads rows via `load_dataset()`.
- For each row:
  - calls `run_classification(narrative=row["narrative"], model_name=model_name)`
  - compares outputs to expected labels:
    - product accuracy: `result.product_category.value == row["expected_product_category"]`
    - issue accuracy: `result.issue_type.value == row["expected_issue_type"]`
  - accumulates confidence
- Returns metrics:
  - total, correct_product, correct_issue
  - product_accuracy, issue_accuracy, avg_confidence

CLI:
- When run as a script, parses `--dataset` and `--model`, runs `evaluate_classification()`, prints JSON.

Note:
- Because `run_classification()` now depends on company context for candidate labels, it includes a fallback:
  - If `company_context` is None, it uses the demo `CompanyKnowledgeService` automatically.

## 10. Prompts and how they relate to the company knowledge layer

### `app/prompts/classification.md`
- Instructs the classifier to select:
  - `product_category` only from company-provided candidates
  - `issue_type` only from company-provided candidates

This prevents the model from inventing new categories outside the internal taxonomy.

### `app/prompts/risk.md`
- Removes generic rubric definitions from prompt.
- Instructs the risk model to use:
  - Company severity rubric candidates
  - Company policy candidates
  - to set `risk_level` and `escalation_required`.

### `app/prompts/resolution.md`
- Resolution agent instructions remain similar, but the user message injected into the agent includes:
  - similar resolution precedents (from pgvector)
  - company policy candidates (from company context)
  - routing candidates
  - and optionally the root-cause hypothesis.

### Compliance and root-cause prompts

- `app/agents/compliance.py` contains a system prompt that:
  - grounds compliance in company policy candidates
  - discourages inventing company-specific rules
- `app/agents/root_cause.py` contains a system prompt that:
  - grounds root-cause inference in control knowledge + evidence trace

## 11. Docker and operational dependencies

- `docker-compose.yml`
  - Runs a Postgres container using `pgvector/pgvector:pg16`
  - Exposes port `5432`
  - Database name is `complaints`

The service uses `DATABASE_URL`:
- default:
  - `postgresql+psycopg2://postgres:postgres@localhost:5432/complaints`

Environment variables:

- `.env.example` documents:
  - `OPENAI_API_KEY` (required for LLM agents)
  - `DATABASE_URL`
  - `EMBEDDING_PROVIDER` plus HuggingFace/OpenAI embedding model names
  - `LOG_LEVEL`, `SQL_ECHO`

Security note:

- Never commit real API keys. `.env.example` currently contains a placeholder-looking value in the repo; treat it as sensitive.

## 12. Important implementation boundaries and coupling points

1. Embedding dimension coupling:
   - `app/db/models.py` sets pgvector column dimensions using `get_embedding_dim()` at import time.
   - If you change embedding provider/model, vector dimensions must match existing tables or you must recreate/migrate.

2. Company knowledge coupling:
   - The architecture provides a boundary (`CompanyKnowledgeService`) where you would later replace the mock pack with:
     - an internal taxonomy store
     - policy/routing rule retrieval
     - severity rubric retrieval
     - root-cause control retrieval

3. Evidence trace explainability:
   - `company_context_node()` creates a base `EvidenceTrace`.
   - `compliance_node()` currently reuses evidence trace snapshot rather than generating new detailed evidence items per compliance result.

4. Persistence coupling:
   - `app/api/routes.py.create_complaint()` writes:
     - enriched company-aware fields into `ComplaintCase`
     - and structured outputs into `Classifications`, `RiskAssessments`, `Resolutions`.

## 13. Documentation generation helpers (repo utilities)

- `generate_repository_architecture_pdf.py`
  - `_markdown_to_lines(md_text)`:
    - converts headings and bullets into (style, line) pairs for simple layout
    - supports fenced code blocks
  - `_wrap_by_chars(text, max_chars)`:
    - deterministic wrapping for PDF generation
  - `render_pdf_from_markdown(md_path, pdf_path)`:
    - uses `reportlab.pdfgen.canvas.Canvas`
    - prints line-by-line, wrapping long lines, and creates new pages when needed

## 14. Summary (how to think about the system)

The repository is not merely a “complaint classifier.” It is an orchestration skeleton for a configurable complaint operating system:

- Portable step: intake normalization + parsing + status updates.
- Company-aware step: retrieve the right knowledge slice and constrain model outputs to internal candidates.
- Evidence + governance: evidence trace and root-cause hypothesis add explainability hooks.
- Persistence: store both structured agent outputs and company-aware operational context.

