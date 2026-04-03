"""LangGraph state definition for the complaint‑processing workflow."""

from __future__ import annotations

from typing import Annotated, Optional

from typing_extensions import TypedDict

from app.schemas.case import CaseRead
from app.schemas.classification import ClassificationResult
from app.schemas.evidence import EvidenceTrace
from app.schemas.resolution import ResolutionRecommendation
from app.schemas.risk import RiskAssessment
from app.schemas.root_cause import RootCauseHypothesis


class WorkflowState(TypedDict, total=False):
    """Shared state passed between nodes in the LangGraph workflow.

    Each key is populated by the corresponding agent node and consumed
    by downstream nodes.
    """

    # ── Input ────────────────────────────────────────────────────────────
    raw_payload: dict  # Original API payload
    company_id: str

    # ── Intake ───────────────────────────────────────────────────────────
    case: CaseRead

    # ── Classification ───────────────────────────────────────────────────
    classification: ClassificationResult
    operational_mapping: dict  # company validation + mapping result
    evidence_trace: EvidenceTrace

    # ── Risk ─────────────────────────────────────────────────────────────
    risk_assessment: RiskAssessment
    company_context: dict  # retrieved company knowledge slices

    # ── Resolution ───────────────────────────────────────────────────────
    resolution: ResolutionRecommendation

    # ── Compliance ───────────────────────────────────────────────────────
    compliance: dict  # {"flags": [...], "passed": bool, "notes": ...}

    # ── Review ───────────────────────────────────────────────────────────
    review: dict  # {"decision": ..., "notes": ..., "suggested_changes": ...}

    # ── Routing ──────────────────────────────────────────────────────────
    routed_to: str

    # ── Root cause ────────────────────────────────────────────────────
    root_cause_hypothesis: RootCauseHypothesis

    # ── Meta ─────────────────────────────────────────────────────────────
    error: Optional[str]
    retry_count: int
