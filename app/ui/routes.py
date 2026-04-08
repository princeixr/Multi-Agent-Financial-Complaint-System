"""HTML view routes for the complaint management dashboard."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db.session import get_db
from app.db.models import (
    ComplaintCase,
    ClassificationRecord,
    RiskRecord,
    ResolutionRecord,
    WorkflowRun,
    WorkflowStep,
)
from app.ui.context import (
    build_case_summary,
    build_case_detail,
    build_analytics_data,
    build_settings_data,
)

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["ui"])


@router.get("/", include_in_schema=False)
async def dashboard(request: Request, page: int = 1, limit: int = 15):
    """Complaint dashboard — paginated list of all complaints."""
    offset = (page - 1) * limit

    with get_db() as db:
        total = db.query(ComplaintCase).count()
        rows = (
            db.query(ComplaintCase)
            .order_by(ComplaintCase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        cases = [build_case_summary(row) for row in rows]

        # KPI counts
        critical_count = (
            db.query(RiskRecord)
            .filter(RiskRecord.risk_level == "critical")
            .count()
        )

    total_pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(request, "dashboard.html", context={
        "cases": cases,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "critical_count": critical_count,
        "active_nav": "dashboard",
    })


@router.get("/complaints/new", include_in_schema=False)
async def lodge_complaint(request: Request):
    """Complaint intake form for manual submission from the UI."""
    return templates.TemplateResponse(request, "lodge.html", context={
        "active_nav": "lodge",
    })


@router.get("/complaints/{case_id}", include_in_schema=False)
async def complaint_detail(request: Request, case_id: str):
    """Single complaint deep-dive with all agent outputs."""
    with get_db() as db:
        db_case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
        if db_case is None:
            return templates.TemplateResponse(request, "detail.html", context={
                "case": None,
                "active_nav": "dashboard",
            })
        case = build_case_detail(db_case)

        # Find associated workflow run for trace link
        run = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.case_id == case_id)
            .order_by(WorkflowRun.started_at.desc())
            .first()
        )
        run_id = run.run_id if run else None

    return templates.TemplateResponse(request, "detail.html", context={
        "case": case,
        "run_id": run_id,
        "active_nav": "dashboard",
    })


@router.get("/trace/latest", include_in_schema=False)
async def latest_trace(request: Request):
    """Resolve sidebar Trace link to the most recent workflow run."""
    with get_db() as db:
        latest = (
            db.query(WorkflowRun)
            .order_by(WorkflowRun.started_at.desc())
            .first()
        )
        latest_run_id = latest.run_id if latest is not None else None

    if latest_run_id is None:
        return templates.TemplateResponse(request, "trace.html", context={
            "run": None,
            "steps": [],
            "total_latency": 0,
            "step_count": 0,
            "active_nav": "trace",
        })

    return RedirectResponse(url=f"/trace/{latest_run_id}", status_code=302)


@router.get("/trace/{run_id}", include_in_schema=False)
async def supervisor_trace(request: Request, run_id: str):
    """Supervisor trace — step-by-step flow visualization."""
    with get_db() as db:
        run_row = db.query(WorkflowRun).filter(WorkflowRun.run_id == run_id).first()
        steps = (
            db.query(WorkflowStep)
            .filter(WorkflowStep.run_id == run_id)
            .order_by(WorkflowStep.sequence_number)
            .all()
        )

        run = None
        if run_row is not None:
            run = {
                "run_id": run_row.run_id,
                "run_status": run_row.run_status,
                "started_at": run_row.started_at,
                "company_id": run_row.company_id,
                "final_route": run_row.final_route,
                "final_severity": run_row.final_severity,
            }

        step_data = []
        for s in steps:
            output = {}
            if s.output_snapshot_json:
                try:
                    output = json.loads(s.output_snapshot_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            step_data.append({
                "node_name": s.node_name,
                "sequence": s.sequence_number,
                "status": s.status,
                "latency_ms": round(s.latency_ms, 1) if s.latency_ms else 0,
                "model_name": s.model_name,
                "confidence": s.confidence,
                "error_type": s.error_type,
                "error_message": s.error_message,
                "output": output,
                "retry_number": s.retry_number,
            })

    total_latency = sum(s["latency_ms"] for s in step_data)

    return templates.TemplateResponse(request, "trace.html", context={
        "run": run,
        "steps": step_data,
        "total_latency": round(total_latency, 1),
        "step_count": len(step_data),
        "active_nav": "trace",
    })


@router.get("/analytics", include_in_schema=False)
async def analytics(request: Request):
    """Analytics overview — charts and KPIs."""
    with get_db() as db:
        data = build_analytics_data(db)

    return templates.TemplateResponse(request, "analytics.html", context={
        "data": data,
        "active_nav": "analytics",
    })


@router.get("/settings", include_in_schema=False)
async def settings(request: Request):
    """Company settings — taxonomy, rubrics, routing rules."""
    data = build_settings_data()

    return templates.TemplateResponse(request, "settings.html", context={
        "data": data,
        "active_nav": "settings",
    })
