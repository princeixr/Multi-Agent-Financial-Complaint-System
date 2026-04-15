"""HTML view routes for the complaint management dashboard."""

from __future__ import annotations

import json
import logging
import uuid
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
    UserAccount,
    WorkflowRun,
    WorkflowStep,
)
from app.ui.context import (
    build_case_summary,
    build_case_detail,
    build_analytics_data,
    build_settings_data,
    build_admin_overview_data,
    _TERMINAL_STATUSES,
)
from app.env_elevenlabs import intake_tts_configured

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["ui"])


def _get_current_user(request: Request) -> dict[str, str | None] | None:
    email = request.cookies.get("username")
    role = request.cookies.get("role")
    if not email or not role:
        return None

    with get_db() as db:
        user = db.query(UserAccount).filter(UserAccount.email == email).first()
        if user is None or user.role != role:
            return None
        return {
            "username": email,
            "role": user.role,
            "company": user.company,
            "user_id": user.user_id,
        }


def _redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


def _redirect_to_dashboard() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


def _post_login_redirect_url(role: str) -> str:
    """End-users land on profile first; admins and team use the app shell home."""
    if role == "user":
        return "/profile"
    return "/"


@router.get("/login", include_in_schema=False)
async def login_form(request: Request, created: str = ""):
    user = _get_current_user(request)
    if user is not None:
        return RedirectResponse(
            url=_post_login_redirect_url(user["role"]),
            status_code=status.HTTP_302_FOUND,
        )

    return templates.TemplateResponse(request, "login.html", context={
        "error": None,
        "success": "Account created! You can now sign in." if created == "1" else None,
        "active_nav": None,
        "user": None,
    })


@router.post("/login", include_in_schema=False)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with get_db() as db:
        user = db.query(UserAccount).filter(UserAccount.email == email).first()
        if user is None:
            return templates.TemplateResponse(request, "login.html", context={
                "error": "No account found with that email.",
                "success": None,
                "active_nav": None,
                "user": None,
            })
        if user.password != password:
            return templates.TemplateResponse(request, "login.html", context={
                "error": "Wrong Password",
                "success": None,
                "active_nav": None,
                "user": None,
            })
        u_email = user.email
        u_role = user.role
        u_user_id = user.user_id
        u_company = user.company

    response = RedirectResponse(
        url=_post_login_redirect_url(u_role),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie("username", u_email, httponly=True)
    response.set_cookie("role", u_role, httponly=True)
    response.set_cookie("user_id", u_user_id, httponly=True)
    if u_company:
        response.set_cookie("company", u_company, httponly=True)
    return response


@router.post("/signup", include_in_schema=False)
async def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with get_db() as db:
        existing = db.query(UserAccount).filter(UserAccount.email == email).first()
        if existing:
            return templates.TemplateResponse(request, "login.html", context={
                "error": "An account with this email already exists.",
                "success": None,
                "active_nav": None,
                "user": None,
                "show_signup": True,
            })

        new_user = UserAccount(
            id=uuid.uuid4().hex,
            email=email,
            password=password,
            role="user",
            company=None,
            user_id=uuid.uuid4().hex,
        )
        db.add(new_user)

    return RedirectResponse(url="/login?created=1", status_code=status.HTTP_302_FOUND)


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
        if user["role"] == "admin":
            overview = build_admin_overview_data(db)
            return templates.TemplateResponse(request, "admin_overview.html", context={
                **overview,
                "active_nav": "dashboard",
                "user": user,
            })

        query = db.query(ComplaintCase).order_by(ComplaintCase.created_at.desc())
        if user["role"] == "team":
            query = query.filter(ComplaintCase.team_assignment == user.get("company"))
        else:
            query = query.filter(ComplaintCase.user_id == user.get("user_id"))

        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        cases = [build_case_summary(row) for row in rows]

        critical_query = db.query(RiskRecord).filter(RiskRecord.risk_level == "critical")
        if user["role"] == "team":
            critical_query = critical_query.join(
                ComplaintCase, ComplaintCase.id == RiskRecord.case_id
            ).filter(ComplaintCase.team_assignment == user.get("company"))
        else:
            critical_query = critical_query.join(
                ComplaintCase, ComplaintCase.id == RiskRecord.case_id
            ).filter(ComplaintCase.user_id == user.get("user_id"))
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


@router.get("/queue", include_in_schema=False)
async def admin_queue(request: Request, page: int = 1, limit: int = 15):
    """Admin complaint queue — full table + resolution history (design: admin_complaint_queue)."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

    offset = (page - 1) * limit

    with get_db() as db:
        query = db.query(ComplaintCase).order_by(ComplaintCase.created_at.desc())
        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        cases = [build_case_summary(row) for row in rows]

        critical_count = (
            db.query(RiskRecord)
            .filter(RiskRecord.risk_level == "critical")
            .count()
        )

        active_pipeline = (
            db.query(ComplaintCase)
            .filter(~ComplaintCase.status.in_(list(_TERMINAL_STATUSES)))
            .count()
        )

        hist_rows = (
            db.query(ComplaintCase)
            .filter(ComplaintCase.status.in_(list(_TERMINAL_STATUSES)))
            .order_by(ComplaintCase.created_at.desc())
            .limit(12)
            .all()
        )
        resolved_history = [build_case_summary(row) for row in hist_rows]

    total_pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(request, "admin_queue.html", context={
        "cases": cases,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "critical_count": critical_count,
        "active_pipeline": active_pipeline,
        "resolved_history": resolved_history,
        "active_nav": "queue",
        "user": user,
    })


@router.get("/profile", include_in_schema=False)
async def user_profile_page(request: Request):
    """End-user account profile and preferences."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "user":
        return _redirect_to_dashboard()

    return templates.TemplateResponse(request, "user_profile.html", context={
        "active_nav": "profile",
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

    return templates.TemplateResponse(request, "lodge.html", context={
        "active_nav": "lodge",
        "user": user,
        "intake_tts_enabled": intake_tts_configured(),
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

        if (
            user["role"] == "team" and db_case.team_assignment != user.get("company")
        ) or (
            user["role"] == "user" and db_case.user_id != user.get("user_id")
        ):
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
            "search_error": "",
            "current_case_id": "",
        })

    return RedirectResponse(url=f"/trace/{latest_run_id}", status_code=302)


@router.get("/trace/search", include_in_schema=False)
async def trace_search(request: Request, case_id: str = ""):
    """Search for a trace by case ID and redirect to it."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

    case_id = case_id.strip().lstrip("#")

    if not case_id:
        return RedirectResponse(url="/trace/latest", status_code=302)

    found_run_id = None

    with get_db() as db:
        # 1. Exact match on WorkflowRun.case_id
        run = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.case_id == case_id)
            .order_by(WorkflowRun.started_at.desc())
            .first()
        )

        # 2. Prefix match on WorkflowRun.case_id
        if run is None:
            run = (
                db.query(WorkflowRun)
                .filter(WorkflowRun.case_id.ilike(f"{case_id}%"))
                .order_by(WorkflowRun.started_at.desc())
                .first()
            )

        # 3. Match via ComplaintCase.id
        if run is None:
            case_row = (
                db.query(ComplaintCase)
                .filter(
                    (ComplaintCase.id == case_id) |
                    ComplaintCase.id.ilike(f"{case_id}%")
                )
                .first()
            )
            if case_row:
                run = (
                    db.query(WorkflowRun)
                    .filter(WorkflowRun.case_id == case_row.id)
                    .order_by(WorkflowRun.started_at.desc())
                    .first()
                )

        # Extract run_id inside the session before it closes
        if run is not None:
            found_run_id = run.run_id

    if found_run_id is None:
        return templates.TemplateResponse(request, "trace.html", context={
            "run": None,
            "steps": [],
            "total_latency": 0,
            "step_count": 0,
            "active_nav": "trace",
            "user": user,
            "search_error": f"No trace found for case ID: #{case_id}",
            "current_case_id": case_id,
        })

    return RedirectResponse(url=f"/trace/{found_run_id}", status_code=302)


@router.get("/trace/suggestions", include_in_schema=False)
async def trace_suggestions(request: Request, q: str = ""):
    """Return live case ID suggestions for the trace search bar."""
    from fastapi.responses import JSONResponse
    user = _get_current_user(request)
    if user is None or user["role"] != "admin":
        return JSONResponse(content=[])

    q = q.strip().lstrip("#")
    if not q:
        return JSONResponse(content=[])

    with get_db() as db:
        # Search WorkflowRun.case_id directly
        runs = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.case_id.ilike(f"{q}%"))
            .order_by(WorkflowRun.started_at.desc())
            .limit(6)
            .all()
        )

        # Also search via ComplaintCase.id if not enough results
        if len(runs) < 6:
            matched_case_ids = {r.case_id for r in runs if r.case_id}
            cases = (
                db.query(ComplaintCase)
                .filter(
                    ComplaintCase.id.ilike(f"{q}%"),
                    ~ComplaintCase.id.in_(matched_case_ids)
                )
                .limit(6 - len(runs))
                .all()
            )
            for c in cases:
                extra_run = (
                    db.query(WorkflowRun)
                    .filter(WorkflowRun.case_id == c.id)
                    .order_by(WorkflowRun.started_at.desc())
                    .first()
                )
                if extra_run:
                    runs.append(extra_run)

        results = [
            {
                "case_id": r.case_id,
                "run_id": r.run_id,
                "run_status": r.run_status,
                "started_at": r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "",
                "final_severity": r.final_severity or "",
            }
            for r in runs if r.case_id
        ]

    return JSONResponse(content=results)


@router.get("/trace/autocomplete", include_in_schema=False)
async def trace_autocomplete(request: Request, q: str = ""):
    """Return matching case IDs and run info for the live autocomplete dropdown."""
    from fastapi.responses import JSONResponse

    user = _get_current_user(request)
    if user is None or user["role"] != "admin":
        return JSONResponse([])

    q = q.strip().lstrip("#")
    if not q:
        return JSONResponse([])

    with get_db() as db:
        runs = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.case_id.startswith(q))
            .order_by(WorkflowRun.started_at.desc())
            .limit(8)
            .all()
        )
        results = [
            {
                "run_id":     r.run_id,
                "case_id":    r.case_id or "",
                "status":     r.run_status or "",
                "severity":   r.final_severity or "",
                "route":      r.final_route or "",
                "started_at": r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "",
            }
            for r in runs
        ]

    return JSONResponse(results)


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
        current_case_id = ""
        if run_row is not None:
            current_case_id = run_row.case_id or ""
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
        "current_case_id": current_case_id,
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


@router.get("/chat-history", include_in_schema=False)
async def chat_history(request: Request, page: int = 1, limit: int = 9):
    """User's intake chat sessions — their past complaint conversations."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] not in ("user",):
        return _redirect_to_dashboard()

    offset = (page - 1) * limit

    with get_db() as db:
        query = (
            db.query(ComplaintCase)
            .filter(ComplaintCase.user_id == user.get("user_id"))
            .order_by(ComplaintCase.created_at.desc())
        )
        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        cases = [build_case_summary(row) for row in rows]

    total_pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(request, "chat_history.html", context={
        "active_nav": "session_history",
        "user": user,
        "cases": cases,
        "total": total,
        "page": page,
        "total_pages": total_pages,
    })


@router.get("/documents", include_in_schema=False)
async def saved_documents(request: Request):
    """User's saved documents — AI-generated resolution briefs."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] not in ("user",):
        return _redirect_to_dashboard()

    import datetime

    with get_db() as db:
        all_cases = (
            db.query(ComplaintCase)
            .filter(ComplaintCase.user_id == user.get("user_id"))
            .order_by(ComplaintCase.created_at.desc())
            .all()
        )
        resolved_cases = [
            build_case_summary(c) for c in all_cases if c.status in ("resolved", "closed")
        ]
        latest_case_obj = all_cases[0] if all_cases else None
        latest_case = build_case_summary(latest_case_obj) if latest_case_obj else None

    return templates.TemplateResponse(request, "saved_documents.html", context={
        "active_nav": "past_complaints",
        "user": user,
        "resolved_cases": resolved_cases,
        "latest_case": latest_case,
        "doc_count": len(resolved_cases),
        "ai_doc_count": len(resolved_cases),
        "today_date": datetime.date.today().strftime("%B %d, %Y"),
    })


@router.get("/resolutions", include_in_schema=False)
async def resolution_history(request: Request):
    """User's resolution history — outcomes of all closed complaints."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] not in ("user",):
        return _redirect_to_dashboard()

    with get_db() as db:
        all_cases = (
            db.query(ComplaintCase)
            .filter(ComplaintCase.user_id == user.get("user_id"))
            .order_by(ComplaintCase.created_at.desc())
            .all()
        )
        resolved_cases_raw = [c for c in all_cases if c.status in ("resolved", "closed", "dismissed")]
        pending_cases_raw = [c for c in all_cases if c.status not in ("resolved", "closed", "dismissed")]

        resolved_cases = [build_case_summary(c) for c in resolved_cases_raw]
        latest_resolution = build_case_summary(resolved_cases_raw[0]) if resolved_cases_raw else None

    return templates.TemplateResponse(request, "resolution_history.html", context={
        "active_nav": "resolutions",
        "user": user,
        "resolved_cases": resolved_cases,
        "latest_resolution": latest_resolution,
        "resolved_count": len(resolved_cases),
        "pending_count": len(pending_cases_raw),
    })


@router.get("/costs", include_in_schema=False)
async def costs(request: Request):
    """Operational cost observability — LLM spend, token usage."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

    return templates.TemplateResponse(request, "costs.html", context={
        "active_nav": "costs",
        "user": user,
    })


@router.get("/team", include_in_schema=False)
async def team(request: Request):
    """Team feedback management — human-in-the-loop reviews."""
    user = _get_current_user(request)
    if user is None:
        return _redirect_to_login()
    if user["role"] != "admin":
        return _redirect_to_dashboard()

    return templates.TemplateResponse(request, "team.html", context={
        "active_nav": "team",
        "user": user,
    })
