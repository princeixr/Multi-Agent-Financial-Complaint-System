"""FastAPI routes for the complaint‑processing service."""

from __future__ import annotations

import logging
import json

from fastapi import APIRouter, HTTPException, status

from app.db.session import get_db
from app.db.models import (
    ComplaintCase,
    ClassificationRecord,
    RiskRecord,
    ResolutionRecord,
)
from app.orchestrator.workflow import process_complaint
from app.schemas.case import CaseCreate, CaseRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["complaints"])


def _json_or_none(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _case_read_from_db(db_case: ComplaintCase) -> CaseRead:
    """Build CaseRead from ORM entities (including related agent outputs)."""
    classification = None
    if db_case.classification is not None:
        classification = {
            "product_category": db_case.classification.product_category,
            "issue_type": db_case.classification.issue_type,
            "sub_issue": db_case.classification.sub_issue,
            "confidence": db_case.classification.confidence,
            "reasoning": db_case.classification.reasoning,
            "keywords": [],
        }

    risk_assessment = None
    if db_case.risk_assessment is not None:
        risk_assessment = {
            "risk_level": db_case.risk_assessment.risk_level,
            "risk_score": db_case.risk_assessment.risk_score,
            "regulatory_risk": db_case.risk_assessment.regulatory_risk,
            "financial_impact_estimate": db_case.risk_assessment.financial_impact_estimate,
            "escalation_required": db_case.risk_assessment.escalation_required,
            "reasoning": db_case.risk_assessment.reasoning,
            "factors": [],
        }

    proposed_resolution = None
    if db_case.resolution is not None:
        proposed_resolution = {
            "recommended_action": db_case.resolution.recommended_action,
            "description": db_case.resolution.description,
            "estimated_resolution_days": db_case.resolution.estimated_resolution_days,
            "monetary_amount": db_case.resolution.monetary_amount,
            "confidence": db_case.resolution.confidence,
            "reasoning": db_case.resolution.reasoning,
            "similar_case_ids": [],
        }

    evidence_trace = (
        json.loads(db_case.evidence_trace_json)
        if db_case.evidence_trace_json
        else None
    )
    external_schema = (
        json.loads(db_case.external_schema_json)
        if db_case.external_schema_json
        else None
    )
    operational_mapping = (
        json.loads(db_case.operational_mapping_json)
        if db_case.operational_mapping_json
        else None
    )
    root_cause_hypothesis = (
        json.loads(db_case.root_cause_hypothesis_json)
        if db_case.root_cause_hypothesis_json
        else None
    )
    compliance_flags = (
        json.loads(db_case.compliance_flags_json)
        if db_case.compliance_flags_json
        else None
    )

    return CaseRead(
        id=db_case.id,
        status=db_case.status,  # CaseStatus conversion happens via pydantic
        consumer_narrative=db_case.consumer_narrative,
        product=db_case.product,
        sub_product=db_case.sub_product,
        company=db_case.company,
        state=db_case.state,
        zip_code=db_case.zip_code,
        channel=db_case.channel,
        submitted_at=db_case.submitted_at,
        created_at=db_case.created_at,
        updated_at=db_case.updated_at,
        classification=classification,
        risk_assessment=risk_assessment,
        proposed_resolution=proposed_resolution,
        compliance_flags=compliance_flags,
        review_notes=db_case.review_notes,
        routed_to=db_case.routed_to,
        external_schema=external_schema,
        operational_mapping=operational_mapping,
        evidence_trace=evidence_trace,
        severity_class=db_case.severity_class,
        team_assignment=db_case.team_assignment,
        sla_class=db_case.sla_class,
        root_cause_hypothesis=root_cause_hypothesis,
    )


@router.post(
    "/complaints",
    response_model=CaseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new consumer complaint",
)
async def create_complaint(payload: CaseCreate) -> CaseRead:
    """Accept a complaint, run it through the full agent pipeline, and return
    the enriched case with classification, risk, resolution, and routing."""
    try:
        final_state = process_complaint(payload.model_dump())
        case: CaseRead = final_state["case"]

        # Persist to database
        with get_db() as db:
            db_case = ComplaintCase(
                id=case.id,
                status=case.status.value,
                consumer_narrative=case.consumer_narrative,
                product=case.product,
                sub_product=case.sub_product,
                company=case.company,
                state=case.state,
                zip_code=case.zip_code,
                channel=case.channel.value,
                submitted_at=case.submitted_at,
                routed_to=case.routed_to,
                team_assignment=case.team_assignment,
                severity_class=case.severity_class,
                sla_class=case.sla_class,
                external_schema_json=_json_or_none(case.external_schema),
                operational_mapping_json=_json_or_none(case.operational_mapping),
                evidence_trace_json=_json_or_none(case.evidence_trace),
                root_cause_hypothesis_json=_json_or_none(case.root_cause_hypothesis),
                compliance_flags_json=_json_or_none(case.compliance_flags),
                review_notes=case.review_notes,
            )
            db.add(db_case)

            # Persist agent outputs into dedicated relational tables.
            if case.classification:
                c = case.classification
                product_category = c.get("product_category")
                if hasattr(product_category, "value"):
                    product_category = product_category.value
                issue_type = c.get("issue_type")
                if hasattr(issue_type, "value"):
                    issue_type = issue_type.value
                db.add(
                    ClassificationRecord(
                        case_id=case.id,
                        product_category=product_category,
                        issue_type=issue_type,
                        sub_issue=c.get("sub_issue"),
                        confidence=c.get("confidence", 0.0),
                        reasoning=c.get("reasoning"),
                    )
                )

            if case.risk_assessment:
                r = case.risk_assessment
                risk_level = r.get("risk_level")
                if hasattr(risk_level, "value"):
                    risk_level = risk_level.value
                db.add(
                    RiskRecord(
                        case_id=case.id,
                        risk_level=risk_level,
                        risk_score=r.get("risk_score", 0.0),
                        regulatory_risk=r.get("regulatory_risk", False),
                        financial_impact_estimate=r.get("financial_impact_estimate"),
                        escalation_required=r.get("escalation_required", False),
                        reasoning=r.get("reasoning"),
                    )
                )

            if case.proposed_resolution:
                res = case.proposed_resolution
                recommended_action = res.get("recommended_action")
                if hasattr(recommended_action, "value"):
                    recommended_action = recommended_action.value
                db.add(
                    ResolutionRecord(
                        case_id=case.id,
                        recommended_action=recommended_action,
                        description=res.get("description", ""),
                        estimated_resolution_days=res.get("estimated_resolution_days", 1),
                        monetary_amount=res.get("monetary_amount"),
                        confidence=res.get("confidence", 0.0),
                        reasoning=res.get("reasoning", ""),
                    )
                )

        # Return the enriched response (and ensure it includes persisted outputs).
        return case

    except Exception as exc:
        logger.exception("Failed to process complaint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Complaint processing failed: {exc}",
        ) from exc


@router.get(
    "/complaints/{case_id}",
    response_model=CaseRead,
    summary="Retrieve a complaint by ID",
)
async def get_complaint(case_id: str) -> CaseRead:
    """Fetch a previously processed complaint case."""
    with get_db() as db:
        db_case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
        if db_case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case {case_id} not found",
            )
        return _case_read_from_db(db_case)


@router.get(
    "/complaints",
    response_model=list[CaseRead],
    summary="List recent complaints",
)
async def list_complaints(limit: int = 20, offset: int = 0) -> list[CaseRead]:
    """Return a paginated list of complaint cases."""
    with get_db() as db:
        rows = (
            db.query(ComplaintCase)
            .order_by(ComplaintCase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_case_read_from_db(row) for row in rows]


@router.get("/health", summary="Health check")
async def health_check() -> dict:
    return {"status": "ok"}
