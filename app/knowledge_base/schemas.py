from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SourceTier = Literal[1, 2, 3, 4]
ValidationStatus = Literal["seeded", "parsed", "review_required", "validated"]


class EffectivePeriod(BaseModel):
    valid_from: str | None = None
    valid_to: str | None = None


class SourceCitation(BaseModel):
    source_family_id: str
    source_url: str | None = None
    document_title: str | None = None
    citation_anchor: str | None = None
    section_path: list[str] = Field(default_factory=list)
    checksum: str | None = None
    retrieval_timestamp: str | None = None
    tier: SourceTier


class NormalizedSection(BaseModel):
    section_id: str
    doc_id: str
    section_path: list[str] = Field(default_factory=list)
    section_title: str
    section_text: str
    citation_anchor: str | None = None
    effective_period: EffectivePeriod = Field(default_factory=EffectivePeriod)
    metadata: dict[str, object] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    doc_id: str
    source_family_id: str
    source_tier: SourceTier
    source_url: str | None = None
    title: str
    regulator: str | None = None
    document_type: str
    publication_date: str | None = None
    effective_date: str | None = None
    version_label: str | None = None
    jurisdiction: str = "US"
    product_scope: list[str] = Field(default_factory=list)
    law_scope: list[str] = Field(default_factory=list)
    raw_text: str = ""
    sections: list[NormalizedSection] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    checksum: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CanonicalObligation(BaseModel):
    obligation_id: str
    label: str
    summary: str
    regulation: str
    regulation_section: str
    trigger_conditions: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    consumer_rights: list[str] = Field(default_factory=list)
    effective_period: EffectivePeriod = Field(default_factory=EffectivePeriod)
    citations: list[SourceCitation] = Field(default_factory=list)
    validation_status: ValidationStatus = "seeded"


class FailureModeMapping(BaseModel):
    failure_mode_id: str
    label: str
    control_domains: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    risk_indicators: list[str] = Field(default_factory=list)
    consumer_harm_types: list[str] = Field(default_factory=list)
    owning_functions: list[str] = Field(default_factory=list)
    remediation_actions: list[str] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    validation_status: ValidationStatus = "seeded"


class ComplaintPrecedentRecord(BaseModel):
    complaint_id: str
    product: str | None = None
    sub_product: str | None = None
    issue: str | None = None
    sub_issue: str | None = None
    company: str | None = None
    response_type: str | None = None
    timeliness: str | None = None
    channel: str | None = None
    geography: str | None = None
    date_received: str | None = None
    narrative_cluster_id: str | None = None
    likely_failure_modes: list[str] = Field(default_factory=list)
    source_citation: SourceCitation
