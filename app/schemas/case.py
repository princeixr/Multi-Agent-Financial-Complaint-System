"""Pydantic models for a consumer‑complaint case."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class CaseStatus(str, Enum):
    RECEIVED = "received"
    INTAKE_COMPLETE = "intake_complete"
    CLASSIFIED = "classified"
    RISK_ASSESSED = "risk_assessed"
    RESOLUTION_PROPOSED = "resolution_proposed"
    COMPLIANCE_CHECKED = "compliance_checked"
    REVIEWED = "reviewed"
    ROUTED = "routed"
    CLOSED = "closed"


class Channel(str, Enum):
    WEB = "web"
    PHONE = "phone"
    EMAIL = "email"
    FAX = "fax"
    POSTAL = "postal"
    REFERRAL = "referral"


# ── Core schema ──────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    """Payload accepted from the API to open a new case."""

    company_id: Optional[str] = Field(
        None, description="Optional company identifier for company-specific routing/policy"
    )

    consumer_narrative: str = Field(
        ..., min_length=10, description="Free‑text complaint narrative"
    )
    product: Optional[str] = Field(None, description="Financial product or service")
    sub_product: Optional[str] = None
    company: Optional[str] = None
    state: Optional[str] = Field(None, max_length=2)
    zip_code: Optional[str] = Field(None, max_length=5)
    channel: Channel = Channel.WEB
    submitted_at: Optional[datetime] = None

    # Optional external labels (e.g., CFPB-provided fields or internal intake
    # classifications). These allow mapping/validation during the company-aware
    # classification step.
    external_product_category: Optional[str] = Field(
        None, description="Optional externally provided product category"
    )
    external_issue_type: Optional[str] = Field(
        None, description="Optional externally provided issue type"
    )
    requested_resolution: Optional[str] = Field(
        None, description="Optional externally requested resolution"
    )


class CaseRead(BaseModel):
    """Full case representation returned by the API."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    status: CaseStatus = CaseStatus.RECEIVED
    consumer_narrative: str
    product: Optional[str] = None
    sub_product: Optional[str] = None
    company: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    channel: Channel = Channel.WEB
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Downstream enrichment (populated by agents)
    classification: Optional[dict] = None
    risk_assessment: Optional[dict] = None
    proposed_resolution: Optional[dict] = None
    compliance_flags: Optional[list[str]] = None
    review_notes: Optional[str] = None
    routed_to: Optional[str] = None

    # New company-aware fields (stored as JSON/dicts for flexibility).
    external_schema: Optional[dict] = None
    operational_mapping: Optional[dict] = None
    evidence_trace: Optional[dict] = None
    severity_class: Optional[str] = None
    team_assignment: Optional[str] = None
    sla_class: Optional[str] = None
    root_cause_hypothesis: Optional[dict] = None

    class Config:
        from_attributes = True
