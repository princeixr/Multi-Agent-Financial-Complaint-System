"""SQLAlchemy ORM models for persistent complaint storage.

Uses pgvector for embedding columns — all vectors, metadata, and application
data live in the same PostgreSQL instance.

Embedding dimension is set by the configured model (see app.retrieval.embeddings):
  - HuggingFace BAAI/bge-small-en-v1.5 (free, local) → 384
  - OpenAI text-embedding-3-small (paid)               → 1 536
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship

from app.retrieval.embeddings import get_embedding_dim

# ── Dimension pulled from the configured embedding model ─────────────────────
EMBEDDING_DIM = get_embedding_dim()


class Base(DeclarativeBase):
    """Shared declarative base for all models."""


# ═════════════════════════════════════════════════════════════════════════════
#  APPLICATION TABLES
# ═════════════════════════════════════════════════════════════════════════════


class UserAccount(Base):
    """Stores registered user accounts backed by PostgreSQL."""

    __tablename__ = "user_accounts"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    email = Column(String(254), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    company = Column(String(200), nullable=True)
    user_id = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ComplaintCase(Base):
    __tablename__ = "complaint_cases"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    status = Column(String(30), nullable=False, default="received")
    consumer_narrative = Column(Text, nullable=False)
    product = Column(String(120))
    sub_product = Column(String(120))
    company = Column(String(200))
    user_id = Column(String(64), nullable=True, index=True)
    state = Column(String(2))
    zip_code = Column(String(5))
    channel = Column(String(20), default="web")
    submitted_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Company-aware operational fields (stored as JSON/text) ─────────
    external_schema_json = Column(Text)
    operational_mapping_json = Column(Text)
    evidence_trace_json = Column(Text)
    severity_class = Column(String(40))
    team_assignment = Column(String(120))
    sla_class = Column(String(40))
    root_cause_hypothesis_json = Column(Text)

    compliance_flags_json = Column(Text)
    review_notes = Column(Text)
    routed_to = Column(String(120))
    classification_audit_json = Column(Text)
    # Snapshot of intake chat + packet when filed via lodge (for user session history)
    intake_session_transcript_json = Column(Text)

    # ── LLM cost tracking ──────────────────────────────────────────────
    token_total = Column(Integer, nullable=True)
    cost_estimate_usd = Column(Float, nullable=True)

    # Relationships
    classification = relationship(
        "ClassificationRecord", back_populates="case", uselist=False
    )
    risk_assessment = relationship(
        "RiskRecord", back_populates="case", uselist=False
    )
    resolution = relationship(
        "ResolutionRecord", back_populates="case", uselist=False
    )


class IntakeSessionRecord(Base):
    __tablename__ = "intake_sessions"

    session_id = Column(String(32), primary_key=True)
    channel = Column(String(20), nullable=False, default="web_chat")
    company_id = Column(String(64), nullable=True)
    turn_index = Column(Integer, nullable=False, default=0)
    packet_json = Column(Text, nullable=False)
    last_agent_message = Column(Text, nullable=False, default="")
    last_user_message = Column(Text, nullable=False, default="")
    conversation_history_json = Column(Text, nullable=False, default="[]")
    completed = Column(Boolean, nullable=False, default=False)
    handoff_triggered = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClassificationRecord(Base):
    __tablename__ = "classifications"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    case_id = Column(String(32), ForeignKey("complaint_cases.id"), nullable=False)
    product_category = Column(String(60), nullable=False)
    issue_type = Column(String(60), nullable=False)
    sub_issue = Column(String(120))
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text)
    review_recommended = Column(Boolean, default=False)
    reason_codes_json = Column(Text)
    keywords_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("ComplaintCase", back_populates="classification")


class RiskRecord(Base):
    __tablename__ = "risk_assessments"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    case_id = Column(String(32), ForeignKey("complaint_cases.id"), nullable=False)
    risk_level = Column(String(20), nullable=False)
    risk_score = Column(Float, nullable=False)
    regulatory_risk = Column(Boolean, default=False)
    financial_impact_estimate = Column(Float)
    escalation_required = Column(Boolean, default=False)
    reasoning = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("ComplaintCase", back_populates="risk_assessment")


class ResolutionRecord(Base):
    __tablename__ = "resolutions"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    case_id = Column(String(32), ForeignKey("complaint_cases.id"), nullable=False)
    recommended_action = Column(String(40), nullable=False)
    description = Column(Text, nullable=False)
    estimated_resolution_days = Column(Float)
    monetary_amount = Column(Float)
    confidence = Column(Float)
    reasoning = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("ComplaintCase", back_populates="resolution")


# ═════════════════════════════════════════════════════════════════════════════
#  VECTOR EMBEDDING TABLES  (pgvector)
# ═════════════════════════════════════════════════════════════════════════════


class ComplaintEmbedding(Base):
    """Historical complaint narratives with their vector embeddings.

    Used by the classification and risk agents to retrieve similar past
    complaints (RAG).  Metadata columns allow efficient pre‑filtering
    before the vector search.
    """

    __tablename__ = "complaint_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    complaint_id = Column(String(20), index=True, comment="Original CFPB complaint ID")
    content = Column(Text, nullable=False, comment="page_content sent to the LLM")
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)

    # ── Filterable metadata ──────────────────────────────────────────────
    product = Column(String(120), index=True)
    sub_product = Column(String(120))
    issue = Column(String(120), index=True)
    sub_issue = Column(String(120))
    company = Column(String(200), index=True)
    state = Column(String(2), index=True)
    zip_code = Column(String(5))
    date_received = Column(String(10))
    submitted_via = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    # ── HNSW index for approximate nearest‑neighbor search ───────────────
    __table_args__ = (
        Index(
            "ix_complaint_embeddings_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class WorkflowRun(Base):
    """One row per LangGraph complaint execution (durable audit)."""

    __tablename__ = "workflow_runs"

    run_id = Column(String(64), primary_key=True)
    case_id = Column(String(32), index=True, nullable=True)
    company_id = Column(String(64), nullable=False)
    trace_id = Column(String(64), index=True, nullable=True)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    run_status = Column(String(40), nullable=False, default="running")
    final_route = Column(String(120), nullable=True)
    final_severity = Column(String(40), nullable=True)
    manual_review_required = Column(Boolean, default=False)
    retry_count_total = Column(Integer, default=0)

    token_total = Column(Integer, nullable=True)
    cost_estimate_total = Column(Float, nullable=True)

    workflow_version = Column(String(32), nullable=True)
    prompt_version = Column(String(64), nullable=True)
    knowledge_pack_version = Column(String(64), nullable=True)
    model_version = Column(String(64), nullable=True)

    steps = relationship("WorkflowStep", back_populates="run")


class WorkflowStep(Base):
    """One row per LangGraph node execution within a run."""

    __tablename__ = "workflow_steps"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    run_id = Column(String(64), ForeignKey("workflow_runs.run_id"), nullable=False, index=True)

    node_name = Column(String(64), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    latency_ms = Column(Float, nullable=True)

    status = Column(String(32), nullable=False, default="success")
    retry_number = Column(Integer, default=0)
    model_name = Column(String(80), nullable=True)

    input_snapshot_json = Column(Text, nullable=True)
    output_snapshot_json = Column(Text, nullable=True)
    state_diff_json = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    error_type = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)

    run = relationship("WorkflowRun", back_populates="steps")


class ResolutionEmbedding(Base):
    """Historical complaint + resolution outcome embeddings.

    Used by the resolution agent to retrieve similar past resolutions as
    precedent for new recommendations.
    """

    __tablename__ = "resolution_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    complaint_id = Column(String(20), index=True, comment="Original CFPB complaint ID")
    content = Column(Text, nullable=False, comment="page_content sent to the LLM")
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)

    # ── Filterable metadata ──────────────────────────────────────────────
    product = Column(String(120), index=True)
    issue = Column(String(120), index=True)
    company = Column(String(200), index=True)
    resolution_outcome = Column(String(100), index=True)
    date_received = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)

    # ── HNSW index for approximate nearest‑neighbor search ───────────────
    __table_args__ = (
        Index(
            "ix_resolution_embeddings_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
