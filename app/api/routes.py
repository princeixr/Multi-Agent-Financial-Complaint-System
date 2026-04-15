"""FastAPI routes for the complaint‑processing service."""

from __future__ import annotations

import logging
import json
from typing import Literal

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.db.models import (
    ComplaintCase,
    ClassificationRecord,
    RiskRecord,
    ResolutionRecord,
)
from app.orchestrator.workflow import process_complaint
from app.schemas.case import CaseCreate, CaseRead
from app.agents.intake_engine import (
    finalize_intake_session,
    get_intake_session,
    process_intake_message,
    start_intake_session,
)
from app.api.elevenlabs_intake import router as elevenlabs_intake_router
from app.api.elevenlabs_intake import synthesize_speech_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["complaints"])
router.include_router(elevenlabs_intake_router)


def _attach_intake_transcript_to_case(case_id: str, session_id: str) -> None:
    """Store lodge intake chat + final packet on the case for user session history."""
    st = get_intake_session(session_id)
    if st is None:
        return
    snap = {
        "session_id": session_id,
        "conversation_history": st.conversation_history,
        "final_packet": json.loads(st.packet.model_dump_json()),
    }
    raw = json.dumps(snap, ensure_ascii=False)
    with get_db() as db:
        row = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
        if row is not None:
            row.intake_session_transcript_json = raw
            db.commit()


def _json_or_none(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_list_from_db(raw: str | None) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _case_read_from_db(db_case: ComplaintCase) -> CaseRead:
    """Build CaseRead from ORM entities (including related agent outputs)."""
    classification = None
    if db_case.classification is not None:
        cr = db_case.classification
        classification = {
            "product_category": cr.product_category,
            "issue_type": cr.issue_type,
            "sub_issue": cr.sub_issue,
            "confidence": cr.confidence,
            "reasoning": cr.reasoning,
            "keywords": _json_list_from_db(getattr(cr, "keywords_json", None)),
            "review_recommended": bool(getattr(cr, "review_recommended", False)),
            "reason_codes": _json_list_from_db(getattr(cr, "reason_codes_json", None)),
            "alternate_candidates": [],
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
    # sub_product is not stored on classifications row; merge from operational_mapping JSON.
    if classification is not None and isinstance(operational_mapping, dict):
        sp = operational_mapping.get("sub_product")
        if sp is not None:
            classification = {**classification, "sub_product": sp}
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

    classification_audit = None
    raw_audit = getattr(db_case, "classification_audit_json", None)
    if raw_audit:
        try:
            classification_audit = json.loads(raw_audit)
        except json.JSONDecodeError:
            classification_audit = None

    cfpb_product = None
    cfpb_sub_product = None
    cfpb_issue = None
    cfpb_sub_issue = None
    if external_schema and isinstance(external_schema, dict):
        cfpb_product = external_schema.get("cfpb_product")
        cfpb_sub_product = external_schema.get("cfpb_sub_product")
        cfpb_issue = external_schema.get("cfpb_issue")
        cfpb_sub_issue = external_schema.get("cfpb_sub_issue")

    return CaseRead(
        id=db_case.id,
        status=db_case.status,  # CaseStatus conversion happens via pydantic
        consumer_narrative=db_case.consumer_narrative,
        product=db_case.product,
        sub_product=db_case.sub_product,
        company=db_case.company,
        user_id=db_case.user_id,
        state=db_case.state,
        zip_code=db_case.zip_code,
        channel=db_case.channel,
        submitted_at=db_case.submitted_at,
        created_at=db_case.created_at,
        updated_at=db_case.updated_at,
        classification=classification,
        classification_audit=classification_audit,
        risk_assessment=risk_assessment,
        proposed_resolution=proposed_resolution,
        compliance_flags=compliance_flags,
        review_notes=db_case.review_notes,
        routed_to=db_case.routed_to,
        cfpb_product=cfpb_product,
        cfpb_sub_product=cfpb_sub_product,
        cfpb_issue=cfpb_issue,
        cfpb_sub_issue=cfpb_sub_issue,
        external_schema=external_schema,
        operational_mapping=operational_mapping,
        evidence_trace=evidence_trace,
        severity_class=db_case.severity_class,
        team_assignment=db_case.team_assignment,
        sla_class=db_case.sla_class,
        root_cause_hypothesis=root_cause_hypothesis,
    )


def _persist_case_and_outputs(case: CaseRead) -> None:
    """Persist CaseRead and specialist outputs into relational tables."""
    with get_db() as db:
        db_case = ComplaintCase(
            id=case.id,
            status=case.status.value,
            consumer_narrative=case.consumer_narrative,
            product=case.product,
            sub_product=case.sub_product,
            company=case.company,
            user_id=case.user_id,
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
            classification_audit_json=_json_or_none(case.classification_audit),
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
                    review_recommended=bool(c.get("review_recommended", False)),
                    reason_codes_json=_json_or_none(c.get("reason_codes")),
                    keywords_json=_json_or_none(c.get("keywords")),
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


def _upsert_case_and_outputs(case: CaseRead) -> None:
    """Insert or update a complaint case and its one-to-one derived outputs."""
    with get_db() as db:
        db_case = db.query(ComplaintCase).filter(ComplaintCase.id == case.id).first()
        if db_case is None:
            db_case = ComplaintCase(id=case.id)
            db.add(db_case)

        db_case.status = case.status.value if hasattr(case.status, "value") else str(case.status)
        db_case.consumer_narrative = case.consumer_narrative or ""
        db_case.product = case.product
        db_case.sub_product = case.sub_product
        db_case.company = case.company
        db_case.user_id = case.user_id
        db_case.state = case.state
        db_case.zip_code = case.zip_code
        db_case.channel = case.channel.value if hasattr(case.channel, "value") else str(case.channel)
        db_case.submitted_at = case.submitted_at
        db_case.routed_to = case.routed_to
        db_case.team_assignment = case.team_assignment
        db_case.severity_class = case.severity_class
        db_case.sla_class = case.sla_class
        db_case.external_schema_json = _json_or_none(case.external_schema)
        db_case.operational_mapping_json = _json_or_none(case.operational_mapping)
        db_case.evidence_trace_json = _json_or_none(case.evidence_trace)
        db_case.root_cause_hypothesis_json = _json_or_none(case.root_cause_hypothesis)
        db_case.compliance_flags_json = _json_or_none(case.compliance_flags)
        db_case.review_notes = case.review_notes
        db_case.classification_audit_json = _json_or_none(case.classification_audit)

        classification_row = (
            db.query(ClassificationRecord)
            .filter(ClassificationRecord.case_id == case.id)
            .first()
        )
        if case.classification:
            c = case.classification
            product_category = c.get("product_category")
            if hasattr(product_category, "value"):
                product_category = product_category.value
            issue_type = c.get("issue_type")
            if hasattr(issue_type, "value"):
                issue_type = issue_type.value
            if classification_row is None:
                classification_row = ClassificationRecord(case_id=case.id)
                db.add(classification_row)
            classification_row.product_category = product_category
            classification_row.issue_type = issue_type
            classification_row.sub_issue = c.get("sub_issue")
            classification_row.confidence = c.get("confidence", 0.0)
            classification_row.reasoning = c.get("reasoning")
            classification_row.review_recommended = bool(c.get("review_recommended", False))
            classification_row.reason_codes_json = _json_or_none(c.get("reason_codes"))
            classification_row.keywords_json = _json_or_none(c.get("keywords"))

        risk_row = db.query(RiskRecord).filter(RiskRecord.case_id == case.id).first()
        if case.risk_assessment:
            r = case.risk_assessment
            risk_level = r.get("risk_level")
            if hasattr(risk_level, "value"):
                risk_level = risk_level.value
            if risk_row is None:
                risk_row = RiskRecord(case_id=case.id)
                db.add(risk_row)
            risk_row.risk_level = risk_level
            risk_row.risk_score = r.get("risk_score", 0.0)
            risk_row.regulatory_risk = r.get("regulatory_risk", False)
            risk_row.financial_impact_estimate = r.get("financial_impact_estimate")
            risk_row.escalation_required = r.get("escalation_required", False)
            risk_row.reasoning = r.get("reasoning")

        resolution_row = (
            db.query(ResolutionRecord)
            .filter(ResolutionRecord.case_id == case.id)
            .first()
        )
        if case.proposed_resolution:
            res = case.proposed_resolution
            recommended_action = res.get("recommended_action")
            if hasattr(recommended_action, "value"):
                recommended_action = recommended_action.value
            if resolution_row is None:
                resolution_row = ResolutionRecord(case_id=case.id)
                db.add(resolution_row)
            resolution_row.recommended_action = recommended_action
            resolution_row.description = res.get("description", "")
            resolution_row.estimated_resolution_days = res.get("estimated_resolution_days", 1)
            resolution_row.monetary_amount = res.get("monetary_amount")
            resolution_row.confidence = res.get("confidence", 0.0)
            resolution_row.reasoning = res.get("reasoning", "")

        db.commit()


def _create_initial_case(case_id: str, payload: CaseCreate, user_id: str | None) -> CaseRead:
    now = datetime.utcnow()
    case = CaseRead(
        id=case_id,
        status="intake_complete",
        consumer_narrative=payload.consumer_narrative or "",
        product=payload.product,
        sub_product=payload.sub_product,
        company=payload.company,
        user_id=user_id,
        state=payload.state,
        zip_code=payload.zip_code,
        channel=payload.channel,
        submitted_at=payload.submitted_at or now,
        created_at=now,
        updated_at=now,
        cfpb_product=payload.cfpb_product,
        cfpb_sub_product=payload.cfpb_sub_product,
        cfpb_issue=payload.cfpb_issue,
        cfpb_sub_issue=payload.cfpb_sub_issue,
        review_notes="Backend processing in progress.",
    )
    _upsert_case_and_outputs(case)
    return case


def _process_case_background(
    *,
    case_id: str,
    payload: dict,
    user_id: str | None,
    session_id: str | None,
) -> None:
    """Run the backend workflow after the user-visible complaint has been registered."""
    try:
        final_state = process_complaint(payload)
        case: CaseRead = final_state["case"]
        case.id = case_id
        case.user_id = user_id
        _upsert_case_and_outputs(case)
        if session_id:
            _attach_intake_transcript_to_case(case_id, session_id)
    except Exception:
        logger.exception("Background complaint processing failed for case_id=%s", case_id)


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
        _persist_case_and_outputs(case)
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


# ── Intake chat endpoints ────────────────────────────────────────────────────


class StartIntakeBody(BaseModel):
    channel: Literal["web_chat", "voice"] = "web_chat"


class IntakeTtsBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice_id: str | None = Field(None, description="Override ELEVENLABS_VOICE_ID for this request.")


@router.post(
    "/intake/session",
    summary="Start a new intake chat session",
)
async def start_intake(body: StartIntakeBody | None = Body(None)) -> dict:
    """Start a channel-agnostic intake session (used by web chat and voice UI)."""
    channel = body.channel if body is not None else "web_chat"
    session_id, state = start_intake_session(channel=channel)
    return {
        "session_id": session_id,
        "agent_message": state.last_agent_message,
        "packet": json.loads(state.packet.model_dump_json()),
    }


@router.post(
    "/intake/tts",
    summary="Synthesize intake agent text for the browser (no Custom LLM bearer)",
    response_class=Response,
)
async def intake_tts(body: IntakeTtsBody) -> Response:
    """ElevenLabs TTS for the lodge UI; uses server-side API key only."""
    audio, content_type = synthesize_speech_bytes(body.text, body.voice_id)
    return Response(content=audio, media_type=content_type)


@router.post(
    "/intake/session/{session_id}/message",
    summary="Send a message to the intake agent and get the next response",
)
async def intake_message(session_id: str, message: str) -> dict:
    """Single-turn chat with the intake agent for an existing session."""
    try:
        state = process_intake_message(session_id=session_id, user_message=message)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown intake session_id={session_id}",
        )
    except Exception as exc:
        logger.exception("Intake engine failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intake processing failed: {exc}",
        ) from exc

    return {
        "session_id": session_id,
        "agent_message": state.last_agent_message,
        "packet": json.loads(state.packet.model_dump_json()),
        "completed": state.completed,
    }


@router.post(
    "/intake/session/{session_id}/finalize",
    summary="Finalize an intake session and open a complaint case",
    response_model=CaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def finalize_intake(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
) -> CaseRead:
    """Turn a completed intake session into a full complaint case."""
    if get_intake_session(session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown intake session_id={session_id}",
        )
    try:
        case_create, _state = finalize_intake_session(session_id)
        case_id = CaseRead().id
        user_id = request.cookies.get("user_id")
        case = _create_initial_case(case_id, case_create, user_id)
        _attach_intake_transcript_to_case(case.id, session_id)
        background_tasks.add_task(
            _process_case_background,
            case_id=case.id,
            payload={**case_create.model_dump(), "case_id": case.id},
            user_id=user_id,
            session_id=session_id,
        )
        return case
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to finalize intake session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intake finalization failed: {exc}",
        ) from exc
