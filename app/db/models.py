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
    UniqueConstraint,
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
    public_case_id = Column(String(16), nullable=True, unique=True, index=True)
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
    jira_issue_key = Column(String(32))
    jira_issue_url = Column(Text)
    classification_audit_json = Column(Text)
    # Snapshot of intake chat + packet when filed via lodge (for user session history)
    intake_session_transcript_json = Column(Text)
    document_gate_result_json = Column(Text)
    document_consistency_json = Column(Text)

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
    documents = relationship(
        "CaseDocument", back_populates="case"
    )
    evaluation_report = relationship(
        "ComplaintEvaluationReport", back_populates="case", uselist=False
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
    documents = relationship("CaseDocument", back_populates="intake_session")


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


class SourceDataset(Base):
    """External or sampled corpora used as the basis for retrieval or benchmarking."""

    __tablename__ = "source_datasets"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    name = Column(String(160), nullable=False, unique=True, index=True)
    company_id = Column(String(64), nullable=False, index=True, default="mock_bank")
    source_type = Column(String(64), nullable=False, default="cfpb")
    description = Column(Text, nullable=True)
    version = Column(String(32), nullable=False, default="v1")
    status = Column(String(32), nullable=False, default="active")
    sampling_strategy_json = Column(Text, nullable=True)
    stats_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("SourceDatasetItem", back_populates="dataset")
    evaluation_datasets = relationship("EvaluationDataset", back_populates="source_dataset")
    knowledge_collections = relationship("KnowledgeCollection", back_populates="source_dataset")


class SourceDatasetItem(Base):
    """One cleaned source row, typically from a stratified CFPB sample."""

    __tablename__ = "source_dataset_items"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    dataset_id = Column(String(32), ForeignKey("source_datasets.id"), nullable=False, index=True)
    external_id = Column(String(64), nullable=True, index=True)
    split = Column(String(32), nullable=False, default="evaluation")
    consumer_narrative = Column(Text, nullable=False)
    product = Column(String(120), nullable=True)
    sub_product = Column(String(120), nullable=True)
    issue = Column(String(120), nullable=True)
    sub_issue = Column(String(120), nullable=True)
    company = Column(String(200), nullable=True)
    state = Column(String(2), nullable=True)
    submitted_via = Column(String(20), nullable=True)
    date_received = Column(String(16), nullable=True)
    company_response = Column(Text, nullable=True)
    company_public_response = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    dataset = relationship("SourceDataset", back_populates="items")


class KnowledgeCollection(Base):
    """Versioned operational knowledge collections, optionally derived from a source dataset."""

    __tablename__ = "knowledge_collections"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    company_id = Column(String(64), nullable=False, index=True, default="mock_bank")
    source_dataset_id = Column(String(32), ForeignKey("source_datasets.id"), nullable=True, index=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    knowledge_type = Column(String(64), nullable=False, default="policy")
    description = Column(Text, nullable=True)
    version = Column(String(32), nullable=False, default="v1")
    status = Column(String(32), nullable=False, default="active")
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_dataset = relationship("SourceDataset", back_populates="knowledge_collections")
    entries = relationship("KnowledgeEntry", back_populates="collection")


class KnowledgeEntry(Base):
    """One knowledge document/snippet inside a knowledge collection."""

    __tablename__ = "knowledge_entries"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    collection_id = Column(String(32), ForeignKey("knowledge_collections.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    collection = relationship("KnowledgeCollection", back_populates="entries")


class KBSourceDocument(Base):
    """Normalized external or internal source document for the knowledge base."""

    __tablename__ = "kb_source_documents"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    source_family_id = Column(String(64), nullable=False, index=True)
    source_tier = Column(Integer, nullable=False, default=1, index=True)
    source_group = Column(String(64), nullable=True, index=True)
    authority_type = Column(String(64), nullable=True)
    source_url = Column(Text, nullable=True)
    title = Column(String(255), nullable=False, index=True)
    regulator = Column(String(120), nullable=True, index=True)
    document_type = Column(String(64), nullable=False, index=True)
    publication_date = Column(String(32), nullable=True, index=True)
    effective_date = Column(String(32), nullable=True, index=True)
    version_label = Column(String(64), nullable=True, index=True)
    jurisdiction = Column(String(32), nullable=False, default="US")
    product_scope_json = Column(Text, nullable=True)
    law_scope_json = Column(Text, nullable=True)
    checksum = Column(String(128), nullable=True, index=True)
    retrieval_timestamp = Column(DateTime, nullable=True, index=True)
    raw_storage_uri = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    ingestion_status = Column(String(32), nullable=False, default="seeded", index=True)
    validation_status = Column(String(32), nullable=False, default="seeded", index=True)
    supersedes_document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supersedes_document = relationship("KBSourceDocument", remote_side=[id])
    sections = relationship("KBDocumentSection", back_populates="document")
    citations = relationship("KBCitation", back_populates="document")
    obligations = relationship("KBObligation", back_populates="document")
    controls = relationship("KBControl", back_populates="document")
    failure_modes = relationship("KBFailureMode", back_populates="document")
    precedent_clusters = relationship("KBPrecedentCluster", back_populates="document")


class KBDocumentSection(Base):
    """Sectionized normalized text derived from a source document."""

    __tablename__ = "kb_document_sections"
    __table_args__ = (
        UniqueConstraint("document_id", "section_key", name="uq_kb_document_section_key"),
    )

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=False, index=True)
    parent_section_id = Column(String(32), ForeignKey("kb_document_sections.id"), nullable=True, index=True)
    section_key = Column(String(255), nullable=False)
    section_title = Column(String(255), nullable=False)
    section_path_json = Column(Text, nullable=True)
    citation_anchor = Column(String(255), nullable=True, index=True)
    section_text = Column(Text, nullable=False)
    effective_from = Column(String(32), nullable=True, index=True)
    effective_to = Column(String(32), nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("KBSourceDocument", back_populates="sections")
    parent_section = relationship("KBDocumentSection", remote_side=[id])
    citations = relationship("KBCitation", back_populates="section")
    obligations = relationship("KBObligation", back_populates="section")


class KBCitation(Base):
    """Reusable citation record pointing to a document and optional section."""

    __tablename__ = "kb_citations"
    __table_args__ = (
        Index("ix_kb_citations_target", "target_table", "target_id"),
    )

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=False, index=True)
    section_id = Column(String(32), ForeignKey("kb_document_sections.id"), nullable=True, index=True)
    target_table = Column(String(64), nullable=False)
    target_id = Column(String(32), nullable=False)
    citation_anchor = Column(String(255), nullable=True)
    quote_text = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("KBSourceDocument", back_populates="citations")
    section = relationship("KBDocumentSection", back_populates="citations")


class KBObligation(Base):
    """Canonical compliance obligation extracted from a regulation or policy source."""

    __tablename__ = "kb_obligations"
    __table_args__ = (
        Index("ix_kb_obligations_reg_section", "regulation", "regulation_section"),
    )

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=True, index=True)
    section_id = Column(String(32), ForeignKey("kb_document_sections.id"), nullable=True, index=True)
    obligation_key = Column(String(128), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    layer = Column(String(32), nullable=False, default="canonical_regulatory_graph", index=True)
    regulation = Column(String(120), nullable=False, index=True)
    regulation_section = Column(String(120), nullable=False, index=True)
    covered_entity_type = Column(String(120), nullable=True, index=True)
    trigger_conditions_json = Column(Text, nullable=True)
    exceptions_json = Column(Text, nullable=True)
    consumer_rights_json = Column(Text, nullable=True)
    required_communications_json = Column(Text, nullable=True)
    effective_from = Column(String(32), nullable=True, index=True)
    effective_to = Column(String(32), nullable=True, index=True)
    source_tier = Column(Integer, nullable=False, default=1)
    validation_status = Column(String(32), nullable=False, default="seeded", index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("KBSourceDocument", back_populates="obligations")
    section = relationship("KBDocumentSection", back_populates="obligations")
    evidence_requirements = relationship("KBEvidenceRequirement", back_populates="obligation")
    deadlines = relationship("KBDeadline", back_populates="obligation")


class KBEvidenceRequirement(Base):
    """Evidence item needed to evaluate or satisfy an obligation."""

    __tablename__ = "kb_evidence_requirements"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    obligation_id = Column(String(32), ForeignKey("kb_obligations.id"), nullable=False, index=True)
    evidence_key = Column(String(128), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    evidence_type = Column(String(64), nullable=True, index=True)
    is_mandatory = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    obligation = relationship("KBObligation", back_populates="evidence_requirements")


class KBDeadline(Base):
    """Timing or response deadline associated with an obligation."""

    __tablename__ = "kb_deadlines"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    obligation_id = Column(String(32), ForeignKey("kb_obligations.id"), nullable=False, index=True)
    deadline_key = Column(String(128), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    duration_text = Column(String(255), nullable=True)
    trigger_event = Column(String(255), nullable=True)
    deadline_type = Column(String(64), nullable=True, index=True)
    rule_text = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    obligation = relationship("KBObligation", back_populates="deadlines")


class KBControl(Base):
    """Operational or supervisory control relevant to complaint handling."""

    __tablename__ = "kb_controls"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=True, index=True)
    control_key = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    control_domain = Column(String(120), nullable=True, index=True)
    control_type = Column(String(64), nullable=True, index=True)
    summary = Column(Text, nullable=True)
    owning_function = Column(String(120), nullable=True, index=True)
    source_tier = Column(Integer, nullable=False, default=2)
    validation_status = Column(String(32), nullable=False, default="seeded", index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("KBSourceDocument", back_populates="controls")
    failure_mode_links = relationship("KBFailureModeControlLink", back_populates="control")


class KBFailureMode(Base):
    """Canonical or supervisory failure mode used by root-cause analysis."""

    __tablename__ = "kb_failure_modes"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=True, index=True)
    failure_mode_key = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    consumer_harm_types_json = Column(Text, nullable=True)
    owning_functions_json = Column(Text, nullable=True)
    remediation_actions_json = Column(Text, nullable=True)
    source_tier = Column(Integer, nullable=False, default=2)
    validation_status = Column(String(32), nullable=False, default="seeded", index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("KBSourceDocument", back_populates="failure_modes")
    control_links = relationship("KBFailureModeControlLink", back_populates="failure_mode")
    risk_links = relationship("KBFailureModeRiskIndicatorLink", back_populates="failure_mode")
    precedent_clusters = relationship("KBPrecedentCluster", back_populates="failure_mode")


class KBRiskIndicator(Base):
    """Risk indicator that can be raised by a failure mode or complaint pattern."""

    __tablename__ = "kb_risk_indicators"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    indicator_key = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    severity_hint = Column(String(32), nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    failure_mode_links = relationship("KBFailureModeRiskIndicatorLink", back_populates="risk_indicator")


class KBFailureModeControlLink(Base):
    """Many-to-many mapping between controls and the failure modes they mitigate."""

    __tablename__ = "kb_failure_mode_control_links"
    __table_args__ = (
        UniqueConstraint("failure_mode_id", "control_id", name="uq_kb_failure_mode_control"),
    )

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    failure_mode_id = Column(String(32), ForeignKey("kb_failure_modes.id"), nullable=False, index=True)
    control_id = Column(String(32), ForeignKey("kb_controls.id"), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False, default="mitigates", index=True)
    strength = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    failure_mode = relationship("KBFailureMode", back_populates="control_links")
    control = relationship("KBControl", back_populates="failure_mode_links")


class KBFailureModeRiskIndicatorLink(Base):
    """Many-to-many mapping between failure modes and risk indicators."""

    __tablename__ = "kb_failure_mode_risk_indicator_links"
    __table_args__ = (
        UniqueConstraint("failure_mode_id", "risk_indicator_id", name="uq_kb_failure_mode_risk"),
    )

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    failure_mode_id = Column(String(32), ForeignKey("kb_failure_modes.id"), nullable=False, index=True)
    risk_indicator_id = Column(String(32), ForeignKey("kb_risk_indicators.id"), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False, default="raises", index=True)
    notes = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    failure_mode = relationship("KBFailureMode", back_populates="risk_links")
    risk_indicator = relationship("KBRiskIndicator", back_populates="failure_mode_links")


class KBPrecedentCluster(Base):
    """Complaint precedent cluster connected to a likely failure mode."""

    __tablename__ = "kb_precedent_clusters"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("kb_source_documents.id"), nullable=True, index=True)
    cluster_key = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    product = Column(String(120), nullable=True, index=True)
    issue = Column(String(120), nullable=True, index=True)
    narrative_signature = Column(Text, nullable=True)
    failure_mode_id = Column(String(32), ForeignKey("kb_failure_modes.id"), nullable=True, index=True)
    complaint_count = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(String(32), nullable=True)
    last_seen_at = Column(String(32), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("KBSourceDocument", back_populates="precedent_clusters")
    failure_mode = relationship("KBFailureMode", back_populates="precedent_clusters")


class EvaluationDataset(Base):
    """Versioned benchmark dataset definition."""

    __tablename__ = "evaluation_datasets"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    source_dataset_id = Column(String(32), ForeignKey("source_datasets.id"), nullable=True, index=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    source = Column(String(64), nullable=False, default="internal")
    version = Column(String(32), nullable=False, default="v1")
    is_gold = Column(Boolean, nullable=False, default=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cases = relationship("EvaluationCase", back_populates="dataset")
    runs = relationship("EvaluationRun", back_populates="dataset")
    source_dataset = relationship("SourceDataset", back_populates="evaluation_datasets")


class EvaluationCase(Base):
    """One benchmark case with canonical inputs and optional document payloads."""

    __tablename__ = "evaluation_cases"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    dataset_id = Column(String(32), ForeignKey("evaluation_datasets.id"), nullable=False, index=True)
    external_case_id = Column(String(64), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    source = Column(String(64), nullable=False, default="synthetic")
    narrative = Column(Text, nullable=False)
    input_payload_json = Column(Text, nullable=False)
    documents_json = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    dataset = relationship("EvaluationDataset", back_populates="cases")
    gold_label = relationship("EvaluationGoldLabel", back_populates="eval_case", uselist=False)
    runs = relationship("EvaluationRun", back_populates="eval_case")


class EvaluationGoldLabel(Base):
    """Human-curated expected outputs and rubric for a benchmark case."""

    __tablename__ = "evaluation_gold_labels"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    eval_case_id = Column(String(32), ForeignKey("evaluation_cases.id"), nullable=False, unique=True, index=True)
    expected_classification_json = Column(Text, nullable=True)
    expected_risk_json = Column(Text, nullable=True)
    expected_root_cause_json = Column(Text, nullable=True)
    expected_resolution_json = Column(Text, nullable=True)
    expected_document_json = Column(Text, nullable=True)
    rubric_json = Column(Text, nullable=True)
    adjudication_notes = Column(Text, nullable=True)
    adjudication_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    eval_case = relationship("EvaluationCase", back_populates="gold_label")


class EvaluationRun(Base):
    """One system-under-test execution against a benchmark case."""

    __tablename__ = "evaluation_runs"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    dataset_id = Column(String(32), ForeignKey("evaluation_datasets.id"), nullable=False, index=True)
    eval_case_id = Column(String(32), ForeignKey("evaluation_cases.id"), nullable=False, index=True)
    execution_mode = Column(String(32), nullable=False, default="workflow")
    run_status = Column(String(32), nullable=False, default="running")
    workflow_run_id = Column(String(64), nullable=True, index=True)
    system_version_json = Column(Text, nullable=True)
    input_snapshot_json = Column(Text, nullable=True)
    output_snapshot_json = Column(Text, nullable=True)
    metrics_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    dataset = relationship("EvaluationDataset", back_populates="runs")
    eval_case = relationship("EvaluationCase", back_populates="runs")
    system_prediction = relationship("EvaluationSystemPrediction", back_populates="eval_run", uselist=False)
    judge_runs = relationship("EvaluationJudgeRun", back_populates="eval_run")
    review_record = relationship("EvaluationReviewRecord", back_populates="eval_run", uselist=False)


class EvaluationSystemPrediction(Base):
    """Normalized system output prepared for judge comparison and UI review."""

    __tablename__ = "evaluation_system_predictions"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    eval_run_id = Column(String(32), ForeignKey("evaluation_runs.id"), nullable=False, unique=True, index=True)
    classification_json = Column(Text, nullable=True)
    predicted_risk_json = Column(Text, nullable=True)
    predicted_root_cause_json = Column(Text, nullable=True)
    predicted_resolution_json = Column(Text, nullable=True)
    predicted_document_json = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    eval_run = relationship("EvaluationRun", back_populates="system_prediction")


class EvaluationJudgeRun(Base):
    """Structured rubric-based evaluator output for a system run."""

    __tablename__ = "evaluation_judge_runs"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    eval_run_id = Column(String(32), ForeignKey("evaluation_runs.id"), nullable=False, index=True)
    judge_name = Column(String(120), nullable=False, default="rubric_judge")
    judge_version = Column(String(32), nullable=False, default="v1")
    run_status = Column(String(32), nullable=False, default="completed")
    rubric_json = Column(Text, nullable=True)
    summary_json = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    eval_run = relationship("EvaluationRun", back_populates="judge_runs")
    review_record = relationship("EvaluationReviewRecord", back_populates="judge_run", uselist=False)


class EvaluationReviewRecord(Base):
    """Normalized review comparison across gold labels, system output, and judge output."""

    __tablename__ = "evaluation_review_records"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    eval_run_id = Column(String(32), ForeignKey("evaluation_runs.id"), nullable=False, unique=True, index=True)
    judge_run_id = Column(String(32), ForeignKey("evaluation_judge_runs.id"), nullable=True, unique=True, index=True)
    overall_status = Column(String(32), nullable=False, default="pending")
    system_vs_gold_json = Column(Text, nullable=True)
    judge_vs_gold_json = Column(Text, nullable=True)
    system_vs_judge_json = Column(Text, nullable=True)
    disagreement_types_json = Column(Text, nullable=True)
    needs_human_review = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    eval_run = relationship("EvaluationRun", back_populates="review_record")
    judge_run = relationship("EvaluationJudgeRun", back_populates="review_record")
    disagreement = relationship("EvaluationDisagreement", back_populates="review_record", uselist=False)


class EvaluationDisagreement(Base):
    """Open disagreement queue item for adjudication."""

    __tablename__ = "evaluation_disagreements"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    review_record_id = Column(String(32), ForeignKey("evaluation_review_records.id"), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="open")
    severity = Column(String(32), nullable=False, default="medium")
    assigned_to = Column(String(120), nullable=True)
    reason_codes_json = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    review_record = relationship("EvaluationReviewRecord", back_populates="disagreement")


class ComplaintEvaluationReport(Base):
    """Stored evaluation report for a real production complaint case."""

    __tablename__ = "complaint_evaluation_reports"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    case_id = Column(String(32), ForeignKey("complaint_cases.id"), nullable=False, unique=True, index=True)
    run_status = Column(String(32), nullable=False, default="completed")
    system_prediction_json = Column(Text, nullable=True)
    system_assessment_json = Column(Text, nullable=True)
    judge_output_json = Column(Text, nullable=True)
    overall_status = Column(String(32), nullable=False, default="pending")
    needs_human_review = Column(Boolean, nullable=False, default=False)
    disagreement_types_json = Column(Text, nullable=True)
    metrics_json = Column(Text, nullable=True)
    judge_reasoning = Column(Text, nullable=True)
    system_reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    evaluated_at = Column(DateTime, nullable=True)

    case = relationship("ComplaintCase", back_populates="evaluation_report")


class CaseDocument(Base):
    __tablename__ = "case_documents"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    case_id = Column(String(32), ForeignKey("complaint_cases.id"), nullable=True, index=True)
    intake_session_id = Column(String(32), ForeignKey("intake_sessions.session_id"), nullable=True, index=True)
    user_id = Column(String(64), nullable=True, index=True)
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(120), nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    storage_uri = Column(Text, nullable=False)
    checksum = Column(String(128), nullable=True, index=True)
    upload_status = Column(String(32), nullable=False, default="uploaded")
    parser_status = Column(String(32), nullable=False, default="pending")
    extraction_status = Column(String(32), nullable=False, default="pending")
    document_type = Column(String(64), nullable=False, default="unknown")
    processing_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    case = relationship("ComplaintCase", back_populates="documents")
    intake_session = relationship("IntakeSessionRecord", back_populates="documents")
    artifact = relationship("DocumentArtifact", back_populates="document", uselist=False)
    embeddings = relationship("DocumentEmbedding", back_populates="document")


class DocumentArtifact(Base):
    __tablename__ = "document_artifacts"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    document_id = Column(String(32), ForeignKey("case_documents.id"), nullable=False, unique=True, index=True)
    raw_text = Column(Text, nullable=True)
    normalized_text = Column(Text, nullable=True)
    extracted_json = Column(Text, nullable=True)
    parser_version = Column(String(64), nullable=True)
    extraction_version = Column(String(64), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("CaseDocument", back_populates="artifact")


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String(32), ForeignKey("case_documents.id"), nullable=False, index=True)
    case_id = Column(String(32), nullable=True, index=True)
    chunk_index = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    source_page = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("CaseDocument", back_populates="embeddings")

    __table_args__ = (
        Index(
            "ix_document_embeddings_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


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

    llm_call_count = Column(Integer, nullable=True)
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

    llm_call_count = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    token_total = Column(Integer, nullable=True)
    cost_estimate_usd = Column(Float, nullable=True)

    input_snapshot_json = Column(Text, nullable=True)
    output_snapshot_json = Column(Text, nullable=True)
    state_diff_json = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    error_type = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)

    run = relationship("WorkflowRun", back_populates="steps")


class LLMCallCost(Base):
    """Atomic ledger entry for one LLM call."""

    __tablename__ = "llm_call_costs"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    run_id = Column(String(64), ForeignKey("workflow_runs.run_id"), nullable=False, index=True)
    case_id = Column(String(32), ForeignKey("complaint_cases.id"), nullable=True, index=True)

    sequence_number = Column(Integer, nullable=True, index=True)
    agent_name = Column(String(64), nullable=True, index=True)
    langsmith_run_id = Column(String(64), nullable=True, index=True)
    provider = Column(String(40), nullable=True)
    model_name = Column(String(120), nullable=True)

    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)

    input_cost_usd = Column(Float, nullable=False, default=0.0)
    output_cost_usd = Column(Float, nullable=False, default=0.0)
    total_cost_usd = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Float, nullable=True)

    status = Column(String(32), nullable=False, default="success")
    retry_number = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    metadata_json = Column(Text, nullable=True)


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
