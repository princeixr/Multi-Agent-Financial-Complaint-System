"""HTML view routes for the complaint management dashboard."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request, Response, Form, status
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
from app.debug_voice_log import dbg_voice
from app.env_elevenlabs import elevenlabs_api_key, elevenlabs_voice_id, intake_tts_configured

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["ui"])

USER_STORE: dict[str, dict[str, str | None]] = {
    "admin": {"password": "admin123", "role": "admin", "company": None, "user_id": "admin-001"},
    "user": {"password": "user123", "role": "user", "company": "Mock Bank", "user_id": "user-001"},
    "rahul": {"password": "rahul123", "role": "user", "company": "Mock Bank", "user_id": "user-002"}
}


def _get_current_user(request: Request) -> dict[str, str | None] | None:
    username = request.cookies.get("username")
    role = request.cookies.get("role")
    if not username or not role:
        return None

    user = USER_STORE.get(username)
    if user is None or user.get("role") != role:
        return None

    return {
        "username": username,
        "role": role,
        "company": user.get("company"),
        "user_id": user.get("user_id"),
    }


def _redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


def _redirect_to_dashboard() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/login", include_in_schema=False)
async def login_form(request: Request):
    user = _get_current_user(request)
    if user is not None:
        return _redirect_to_dashboard()

    return templates.TemplateResponse(request, "login.html", context={
        "error": None,
        "active_nav": None,
        "user": None,
    })


@router.post("/login", include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = USER_STORE.get(username)
    if not user or user["password"] != password:
        return templates.TemplateResponse(request, "login.html", context={
            "error": "Invalid username or password.",
            "active_nav": None,
            "user": None,
        })

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie("username", username, httponly=True)
    response.set_cookie("role", user["role"], httponly=True)
    response.set_cookie("user_id", user["user_id"], httponly=True)
    if user.get("company"):
        response.set_cookie("company", user["company"], httponly=True)
    return response


@router.get("/logout", include_in_schema=False)
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("username")
    response.delete_cookie("role")
    response.delete_cookie("company")
    response.delete_cookie("user_id")
    return response


@router.get("/", include_in_schema=False)
async def home_or_dashboard(request: Request, page: int = 1, limit: int = 15):
    """Show the public homepage when unauthenticated, else render the complaint dashboard."""
    user = _get_current_user(request)
    if user is None:
        return templates.TemplateResponse(request, "home.html", context={
            "active_nav": None,
            "user": None,
        })

    offset = (page - 1) * limit

    with get_db() as db:
        query = db.query(ComplaintCase).order_by(ComplaintCase.created_at.desc())
        if user["role"] != "admin":
            query = query.filter(ComplaintCase.user_id == user.get("user_id"))

        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        cases = [build_case_summary(row) for row in rows]

        # KPI counts
        critical_query = db.query(RiskRecord).filter(RiskRecord.risk_level == "critical")
        if user["role"] != "admin":
            critical_query = critical_query.join(ComplaintCase, ComplaintCase.id == RiskRecord.case_id).filter(
                ComplaintCase.user_id == user.get("user_id")
            )
        critical_count = critical_query.count()

    total_pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(request, "dashboard.html", context={
        "cases": cases,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "critical_count": critical_count,
        "active_nav": "dashboard",
        "user": user,
    })


@router.get("/brand", include_in_schema=False)
async def brand_page(request: Request):
    return templates.TemplateResponse(request, "brand.html", context={
        "active_nav": None,
        "user": _get_current_user(request),
    })


@router.get("/complaints/new", include_in_schema=False)
async def lodge_complaint(request: Request):
    """Complaint intake form for manual submission from the UI."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()

    # region agent log
    _tts = intake_tts_configured()
    _k = elevenlabs_api_key()
    _v = elevenlabs_voice_id()
    dbg_voice(
        "H1",
        "ui/routes:lodge_complaint",
        "lodge_tts_flags",
        {
            "intake_tts_configured": _tts,
            "api_key_len": len(_k) if _k else 0,
            "voice_id_len": len(_v) if _v else 0,
            "tts_missing_reason": (
                "missing_api_key"
                if not _k
                else "missing_voice_id"
                if not _v
                else "configured"
            ),
        },
    )
    # endregion
    return templates.TemplateResponse(request, "lodge.html", context={
        "active_nav": "lodge",
        "user": user,
        "intake_tts_enabled": _tts,
    })


@router.get("/complaints/{case_id}", include_in_schema=False)
async def complaint_detail(request: Request, case_id: str):
    """Single complaint deep-dive with all agent outputs."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()

    with get_db() as db:
        db_case = db.query(ComplaintCase).filter(ComplaintCase.id == case_id).first()
        if db_case is None:
            return templates.TemplateResponse(request, "detail.html", context={
                "case": None,
                "active_nav": "dashboard",
                "user": user,
            })

        if user["role"] != "admin" and db_case.user_id != user.get("user_id"):
            return templates.TemplateResponse(request, "detail.html", context={
                "case": None,
                "active_nav": "dashboard",
                "user": user,
                "access_denied": True,
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
        "user": user,
    })


@router.get("/trace/latest", include_in_schema=False)
async def latest_trace(request: Request):
    """Resolve sidebar Trace link to the most recent workflow run."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

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
            "user": user,
        })

    return RedirectResponse(url=f"/trace/{latest_run_id}", status_code=302)


@router.get("/trace/{run_id}", include_in_schema=False)
async def supervisor_trace(request: Request, run_id: str):
    """Supervisor trace — step-by-step flow visualization."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

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

            input_data = {}
            if s.input_snapshot_json:
                try:
                    input_data = json.loads(s.input_snapshot_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            state_diff = {}
            if s.state_diff_json:
                try:
                    state_diff = json.loads(s.state_diff_json)
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
                "input": input_data,
                "state_diff": state_diff,
                "retry_number": s.retry_number,
                "started_at": s.started_at.strftime("%H:%M:%S") if s.started_at else None,
                "ended_at": s.ended_at.strftime("%H:%M:%S") if s.ended_at else None,
            })

    total_latency = sum(s["latency_ms"] for s in step_data)

    return templates.TemplateResponse(request, "trace.html", context={
        "run": run,
        "steps": step_data,
        "total_latency": round(total_latency, 1),
        "step_count": len(step_data),
        "active_nav": "trace",
        "user": user,
    })


@router.get("/analytics", include_in_schema=False)
async def analytics(request: Request):
    """Analytics overview — charts and KPIs."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

    with get_db() as db:
        data = build_analytics_data(db)

    return templates.TemplateResponse(request, "analytics.html", context={
        "data": data,
        "active_nav": "analytics",
        "user": user,
    })


@router.get("/settings", include_in_schema=False)
async def settings(request: Request):
    """Company settings — taxonomy, rubrics, routing rules."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

    data = build_settings_data()

    return templates.TemplateResponse(request, "settings.html", context={
        "data": data,
        "active_nav": "settings",
        "user": user,
    })
