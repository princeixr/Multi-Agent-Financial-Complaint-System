"""Template context builders — query DB and format data for Jinja2 templates."""

from __future__ import annotations

import json
import logging
from collections import Counter

from sqlalchemy.orm import Session

from app.db.models import (
    ComplaintCase,
    ClassificationRecord,
    RiskRecord,
    ResolutionRecord,
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


def build_case_summary(db_case: ComplaintCase) -> dict:
    """Build a lightweight summary dict for the dashboard table."""
    cls = db_case.classification
    risk = db_case.risk_assessment

    narrative = db_case.consumer_narrative or ""
    subject = narrative[:200] + "..." if len(narrative) > 200 else narrative

    return {
        "id": db_case.id,
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

    return {
        "total_complaints": total_complaints,
        "avg_resolution_seconds": round(avg_resolution, 1),
        "category_counts": dict(category_counts.most_common(10)),
        "risk_counts": dict(risk_counts),
        "team_counts": dict(team_counts.most_common(10)),
        "resolution_times": resolution_times[:20],
    }


def build_settings_data() -> dict:
    """Load company knowledge for the settings view."""
    try:
        from app.knowledge import CompanyKnowledgeService
        svc = CompanyKnowledgeService(company_id="mock_bank")
        ctx = svc.build_company_context("")

        return {
            "company_id": "mock_bank",
            "taxonomy": ctx.taxonomy_candidates,
            "severity_rubric": ctx.severity_candidates,
            "routing_rules": ctx.routing_candidates,
            "root_cause_controls": ctx.root_cause_controls,
            "policy_snippets": ctx.policy_candidates,
        }
    except Exception as e:
        logger.warning("Could not load company knowledge: %s", e)
        return {
            "company_id": "mock_bank",
            "taxonomy": {},
            "severity_rubric": [],
            "routing_rules": {},
            "root_cause_controls": [],
            "policy_snippets": [],
        }