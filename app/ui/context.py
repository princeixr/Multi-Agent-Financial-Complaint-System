"""Template context builders — query DB and format data for Jinja2 templates."""

from __future__ import annotations

import json
import logging
from collections import Counter

from sqlalchemy.orm import Session

from app.documents.service import build_case_document_summary
from app.evals.service import (
    build_evaluation_case_detail as _build_evaluation_case_detail,
    build_evaluation_dashboard_data as _build_evaluation_dashboard_data,
)
from app.db.models import (
    ComplaintCase,
    ClassificationRecord,
    RiskRecord,
    WorkflowRun,
)

logger = logging.getLogger(__name__)


def _safe_json_load(value: str | None) -> dict | list | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_supporting_documents(transcript: dict | None) -> list[dict]:
    if not isinstance(transcript, dict):
        return []

    candidates: list[object] = []
    final_packet = transcript.get("final_packet")
    if isinstance(final_packet, dict):
        candidates.extend([
            final_packet.get("documents"),
            final_packet.get("attachments"),
            final_packet.get("uploaded_files"),
            final_packet.get("files"),
        ])
        intake_case = final_packet.get("intake_case")
        if isinstance(intake_case, dict):
            candidates.extend([
                intake_case.get("documents"),
                intake_case.get("attachments"),
                intake_case.get("uploaded_files"),
                intake_case.get("files"),
            ])

    documents: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if isinstance(item, dict):
                documents.append(item)
            elif isinstance(item, str):
                documents.append({"name": item})
    return documents


def _document_rows_from_case(db_case: ComplaintCase) -> list[dict]:
    docs = []
    for row in getattr(db_case, "documents", []) or []:
        artifact = getattr(row, "artifact", None)
        extracted = _safe_json_load(getattr(artifact, "extracted_json", None)) if artifact else {}
        docs.append({
            "id": row.id,
            "name": row.original_filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "upload_status": row.upload_status,
            "parser_status": row.parser_status,
            "extraction_status": row.extraction_status,
            "document_type": row.document_type,
            "processing_error": row.processing_error,
            "facts": extracted if isinstance(extracted, dict) else {},
        })
    return docs


def build_case_summary(db_case: ComplaintCase) -> dict:
    """Build a lightweight summary dict for the dashboard table."""
    cls = db_case.classification
    risk = db_case.risk_assessment

    narrative = db_case.consumer_narrative or ""
    subject = narrative[:200] + "..." if len(narrative) > 200 else narrative

    res = db_case.resolution
    transcript = _safe_json_load(getattr(db_case, "intake_session_transcript_json", None))
    final_packet = transcript.get("final_packet") if isinstance(transcript, dict) else None
    conversation_history = (
        transcript.get("conversation_history")
        if isinstance(transcript, dict) and isinstance(transcript.get("conversation_history"), list)
        else []
    )
    supporting_documents = _document_rows_from_case(db_case) or _extract_supporting_documents(transcript)
    document_summary = build_case_document_summary(db_case.id) if db_case.id else None

    created = db_case.created_at
    updated = db_case.updated_at
    if created and updated and updated > created:
        delta = updated - created
        total_seconds = int(delta.total_seconds())
        if total_seconds < 3600:
            total_time_str = f"{total_seconds // 60}m"
        elif total_seconds < 86400:
            h, m = divmod(total_seconds // 60, 60)
            total_time_str = f"{h}h {m}m" if m else f"{h}h"
        else:
            days = total_seconds // 86400
            h = (total_seconds % 86400) // 3600
            total_time_str = f"{days}d {h}h" if h else f"{days}d"
    else:
        total_time_str = None

    return {
        "id": db_case.id,
        "public_case_id": getattr(db_case, "public_case_id", None) or db_case.id[:12].upper(),
        "subject": subject,
        "status": db_case.status or "unknown",
        "product": cls.product_category if cls else None,
        "sub_product": db_case.sub_product,
        "risk_level": risk.risk_level if risk else None,
        "risk_score": risk.risk_score if risk else None,
        "confidence": cls.confidence if cls else None,
        "routed_to": db_case.routed_to,
        "team_assignment": db_case.team_assignment,
        "created_at": db_case.created_at,
        "severity_class": db_case.severity_class,
        "total_time_str": total_time_str,
        "estimated_resolution_days": res.estimated_resolution_days if res else None,
        "monetary_amount": res.monetary_amount if res else None,
        "intake_session_transcript": transcript if isinstance(transcript, dict) else None,
        "conversation_history": conversation_history,
        "intake_payload": final_packet if isinstance(final_packet, dict) else None,
        "supporting_documents": supporting_documents,
        "has_supporting_docs": (
            bool(supporting_documents) or bool(final_packet.get("has_supporting_docs"))
            if isinstance(final_packet, dict)
            else bool(supporting_documents)
        ),
        "document_summary": document_summary.model_dump() if document_summary else {},
    }


_TERMINAL_STATUSES = frozenset({"resolved", "closed", "dismissed"})


def build_admin_overview_data(db: Session) -> dict:
    """KPIs and recent rows for the admin operational intelligence overview."""
    total = db.query(ComplaintCase).count()
    resolved_count = (
        db.query(ComplaintCase)
        .filter(ComplaintCase.status.in_(list(_TERMINAL_STATUSES)))
        .count()
    )
    active_count = max(0, total - resolved_count)

    critical_count = db.query(RiskRecord).filter(RiskRecord.risk_level == "critical").count()

    recent = (
        db.query(ComplaintCase)
        .order_by(ComplaintCase.created_at.desc())
        .limit(8)
        .all()
    )
    recent_queue = [build_case_summary(row) for row in recent]

    resolution_rate = round(100.0 * resolved_count / total, 1) if total else 0.0

    return {
        "total": total,
        "active_count": active_count,
        "resolved_count": resolved_count,
        "critical_count": critical_count,
        "resolution_rate": resolution_rate,
        "recent_queue": recent_queue,
    }


def build_case_detail(db_case: ComplaintCase) -> dict:
    """Build a full detail dict for the complaint detail view."""
    cls = db_case.classification
    risk = db_case.risk_assessment
    res = db_case.resolution

    classification = None
    if cls:
        classification = {
            "product_category": cls.product_category,
            "issue_type": cls.issue_type,
            "sub_issue": cls.sub_issue,
            "confidence": cls.confidence,
            "reasoning": cls.reasoning,
        }

    risk_assessment = None
    if risk:
        risk_assessment = {
            "risk_level": risk.risk_level,
            "risk_score": risk.risk_score,
            "regulatory_risk": risk.regulatory_risk,
            "financial_impact_estimate": risk.financial_impact_estimate,
            "escalation_required": risk.escalation_required,
            "reasoning": risk.reasoning,
        }

    resolution = None
    if res:
        resolution = {
            "recommended_action": res.recommended_action,
            "description": res.description,
            "estimated_resolution_days": res.estimated_resolution_days,
            "monetary_amount": res.monetary_amount,
            "confidence": res.confidence,
            "reasoning": res.reasoning,
        }

    return {
        "id": db_case.id,
        "public_case_id": getattr(db_case, "public_case_id", None) or db_case.id[:12].upper(),
        "status": db_case.status or "unknown",
        "consumer_narrative": db_case.consumer_narrative,
        "product": db_case.product,
        "sub_product": db_case.sub_product,
        "company": db_case.company,
        "state": db_case.state,
        "zip_code": db_case.zip_code,
        "channel": db_case.channel,
        "submitted_at": db_case.submitted_at,
        "created_at": db_case.created_at,
        "classification": classification,
        "risk_assessment": risk_assessment,
        "resolution": resolution,
        "root_cause_hypothesis": _safe_json_load(db_case.root_cause_hypothesis_json),
        "compliance_flags": _safe_json_load(db_case.compliance_flags_json),
        "review_notes": db_case.review_notes,
        "routed_to": db_case.routed_to,
        "team_assignment": db_case.team_assignment,
        "severity_class": db_case.severity_class,
        "document_gate_result": _safe_json_load(getattr(db_case, "document_gate_result_json", None)),
        "document_consistency": _safe_json_load(getattr(db_case, "document_consistency_json", None)),
        "intake_session_transcript": _safe_json_load(
            getattr(db_case, "intake_session_transcript_json", None)
        ),
        "case_documents": _document_rows_from_case(db_case),
        "case_document_summary": build_case_document_summary(db_case.id).model_dump() if db_case.id else {},
    }


def build_analytics_data(db: Session) -> dict:
    """Build aggregate analytics data for the analytics dashboard."""
    total_complaints = db.query(ComplaintCase).count()

    # Complaints by product category
    category_rows = (
        db.query(ClassificationRecord.product_category)
        .all()
    )
    category_counts = Counter(r[0] for r in category_rows if r[0])

    # Risk distribution
    risk_rows = db.query(RiskRecord.risk_level).all()
    risk_counts = Counter(r[0] for r in risk_rows if r[0])

    # Team workload
    team_rows = (
        db.query(ComplaintCase.routed_to)
        .filter(ComplaintCase.routed_to.isnot(None))
        .all()
    )
    team_counts = Counter(r[0] for r in team_rows)

    # Recent runs for resolution time
    runs = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.ended_at.isnot(None))
        .order_by(WorkflowRun.started_at.desc())
        .limit(50)
        .all()
    )
    resolution_times = []
    for run in runs:
        if run.started_at and run.ended_at:
            delta = (run.ended_at - run.started_at).total_seconds()
            resolution_times.append({
                "date": run.started_at.strftime("%Y-%m-%d"),
                "seconds": round(delta, 1),
            })

    avg_resolution = (
        sum(r["seconds"] for r in resolution_times) / len(resolution_times)
        if resolution_times else 0
    )

    recent_rows = (
        db.query(ComplaintCase)
        .order_by(ComplaintCase.created_at.desc())
        .limit(10)
        .all()
    )
    recent_cases = [build_case_summary(row) for row in recent_rows]

    return {
        "total_complaints": total_complaints,
        "avg_resolution_seconds": round(avg_resolution, 1),
        "category_counts": dict(category_counts.most_common(10)),
        "risk_counts": dict(risk_counts),
        "team_counts": dict(team_counts.most_common(10)),
        "resolution_times": resolution_times[:20],
        "recent_cases": recent_cases,
    }


def build_settings_data() -> dict:
    """Load knowledge pack content for the settings view."""
    try:
        from app.knowledge import CompanyKnowledgeService
        from app.knowledge.mock_company_pack import deployment_label

        svc = CompanyKnowledgeService()
        ctx = svc.build_company_context("")

        return {
            "deployment": deployment_label(),
            "taxonomy": ctx.taxonomy_candidates,
            "severity_rubric": ctx.severity_candidates,
            "routing_rules": ctx.routing_candidates,
            "root_cause_controls": ctx.root_cause_controls,
            "policy_snippets": ctx.policy_candidates,
        }
    except Exception as e:
        logger.warning("Could not load company knowledge: %s", e)
        return {
            "deployment": "unknown",
            "taxonomy": {},
            "severity_rubric": [],
            "routing_rules": {},
            "root_cause_controls": [],
            "policy_snippets": [],
        }


def build_evaluation_data() -> dict:
    """Load benchmark datasets, recent eval runs, and disagreement queue."""
    try:
        return _build_evaluation_dashboard_data()
    except Exception as e:
        logger.warning("Could not load evaluation dashboard data: %s", e)
        return {
            "terms": [],
            "source_datasets": [],
            "datasets": [],
            "recent_runs": [],
            "open_disagreements": [],
            "coverage": {
                "products": {},
                "issues": {},
                "narrative_lengths": {},
            },
            "dimension_scores": {
                "system_vs_gold": [],
                "judge_vs_gold": [],
            },
            "disagreement_reason_counts": {},
            "summary": {
                "source_dataset_count": 0,
                "dataset_count": 0,
                "recent_run_count": 0,
                "open_disagreement_count": 0,
                "pass_count": 0,
                "needs_review_count": 0,
                "fail_count": 0,
            },
        }


def build_evaluation_case_data(eval_case_id: str) -> dict | None:
    """Load the full evaluation-case detail payload."""
    try:
        return _build_evaluation_case_detail(eval_case_id)
    except Exception as e:
        logger.warning("Could not load evaluation case detail: %s", e)
        return None
