"""Agentic LangGraph workflow — supervisor-driven complaint processing.

Hub-and-spoke architecture: a supervisor LLM decides which specialist
agent to invoke next. Specialists use tools to autonomously retrieve
context (similar complaints, policies, taxonomy, etc.).
"""

from __future__ import annotations

import json
import logging
import uuid

from langgraph.graph import END, StateGraph
from opentelemetry.trace import Status, StatusCode

from app.agents.classification import run_classification
from app.agents.compliance import run_compliance_check
from app.agents.intake import run_intake
from app.agents.resolution import run_resolution
from app.agents.review import run_review
from app.agents.risk import run_risk_assessment
from app.agents.root_cause import run_root_cause_hypothesis
from app.agents.routing import run_routing
from app.agents.supervisor import run_supervisor
from app.observability.context import ActiveRun, reset_active_run, set_active_run, set_trace_id
from app.observability.events import log_workflow_event
from app.observability.instrumentation import wrap_node, wrap_supervisor_node
from app.observability.persistence import (
    derive_run_outcome,
    finalize_workflow_run,
    insert_workflow_run,
)
from app.observability.tracing import get_workflow_tracer, setup_tracing, trace_id_hex_from_span
from app.observability.versions import workflow_version
from app.orchestrator.state import WorkflowState
from app.schemas.case import CaseCreate, CaseStatus

logger = logging.getLogger(__name__)

# Node names that avoid collisions with WorkflowState keys.
# LangGraph does not allow a node name to match a state key.
_NODE_CLASSIFY = "classify"
_NODE_RISK = "risk"
_NODE_ROOT_CAUSE = "root_cause"
_NODE_RESOLVE = "resolve"
_NODE_COMPLIANCE = "check_compliance"
_NODE_REVIEW = "qa_review"
_NODE_ROUTE = "route"

# Supervisor knows these names for routing decisions
SPECIALIST_NODES = frozenset(
    {_NODE_CLASSIFY, _NODE_RISK, _NODE_ROOT_CAUSE, _NODE_RESOLVE,
     _NODE_COMPLIANCE, _NODE_REVIEW, _NODE_ROUTE}
)


# ── Node functions ───────────────────────────────────────────────────────────

def intake_node(state: WorkflowState) -> WorkflowState:
    """Deterministic intake: PII redaction, validation, normalisation."""
    payload = CaseCreate(**state["raw_payload"])
    case = run_intake(payload)
    return {
        **state,
        "case": case,
        "completed_steps": [],
        "step_count": 0,
        "max_steps": state.get("max_steps", 15),
    }


def supervisor_node(state: WorkflowState):
    """Supervisor: decides which specialist to invoke next. Returns Command."""
    return run_supervisor(state)


def classify_node(state: WorkflowState) -> WorkflowState:
    """Classification specialist with tool access."""
    case = state["case"]
    company_id = state.get("company_id", "mock_bank")
    instructions = state.get("supervisor_instructions", "")

    result = run_classification(
        narrative=case.consumer_narrative,
        product=case.product,
        sub_product=case.sub_product,
        company=case.company,
        state=case.state,
        company_id=company_id,
        instructions=instructions,
    )

    case.classification = result.model_dump()
    case.status = CaseStatus.CLASSIFIED
    case.operational_mapping = {
        "product_category": result.product_category.value,
        "issue_type": result.issue_type.value,
        "sub_issue": result.sub_issue,
    }

    completed = list(state.get("completed_steps", []))
    completed.append("classify")

    return {**state, "case": case, "classification": result, "completed_steps": completed}


def risk_node(state: WorkflowState) -> WorkflowState:
    """Risk assessment specialist with tool access."""
    case = state["case"]
    company_id = state.get("company_id", "mock_bank")
    instructions = state.get("supervisor_instructions", "")

    result = run_risk_assessment(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        company_id=company_id,
        instructions=instructions,
    )

    case.risk_assessment = result.model_dump()
    case.severity_class = result.risk_level.value
    case.status = CaseStatus.RISK_ASSESSED

    completed = list(state.get("completed_steps", []))
    completed.append("risk")

    return {**state, "case": case, "risk_assessment": result, "completed_steps": completed}


def root_cause_node(state: WorkflowState) -> WorkflowState:
    """Root cause hypothesis specialist with tool access."""
    case = state["case"]
    company_id = state.get("company_id", "mock_bank")
    instructions = state.get("supervisor_instructions", "")

    result = run_root_cause_hypothesis(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        risk=state["risk_assessment"],
        company_id=company_id,
        instructions=instructions,
    )

    case.root_cause_hypothesis = result.model_dump()

    completed = list(state.get("completed_steps", []))
    completed.append("root_cause")

    return {**state, "case": case, "root_cause_hypothesis": result, "completed_steps": completed}


def resolution_node(state: WorkflowState) -> WorkflowState:
    """Resolution specialist with tool access."""
    case = state["case"]
    company_id = state.get("company_id", "mock_bank")
    instructions = state.get("supervisor_instructions", "")

    result = run_resolution(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        risk=state["risk_assessment"],
        root_cause_hypothesis=state.get("root_cause_hypothesis"),
        company_id=company_id,
        instructions=instructions,
    )

    case.proposed_resolution = result.model_dump()
    case.status = CaseStatus.RESOLUTION_PROPOSED

    completed = list(state.get("completed_steps", []))
    completed.append("resolve")

    return {**state, "case": case, "resolution": result, "completed_steps": completed}


def compliance_node(state: WorkflowState) -> WorkflowState:
    """Compliance specialist with tool access."""
    case = state["case"]
    company_id = state.get("company_id", "mock_bank")
    instructions = state.get("supervisor_instructions", "")

    result = run_compliance_check(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        risk=state["risk_assessment"],
        resolution=state["resolution"],
        company_id=company_id,
        instructions=instructions,
    )

    case.compliance_flags = result.get("flags", [])
    case.status = CaseStatus.COMPLIANCE_CHECKED

    completed = list(state.get("completed_steps", []))
    completed.append("check_compliance")

    return {**state, "case": case, "compliance": result, "completed_steps": completed}


def review_node(state: WorkflowState) -> WorkflowState:
    """Review specialist — QA pass with structured feedback."""
    case = state["case"]
    instructions = state.get("supervisor_instructions", "")

    result = run_review(
        narrative=case.consumer_narrative,
        classification_json=json.dumps(state["classification"].model_dump()),
        risk_json=json.dumps(state["risk_assessment"].model_dump()),
        resolution_json=json.dumps(state["resolution"].model_dump()),
        compliance_json=json.dumps(state.get("compliance", {})),
        instructions=instructions,
    )

    case.review_notes = result.get("notes", "")
    case.status = CaseStatus.REVIEWED

    completed = list(state.get("completed_steps", []))
    completed.append("qa_review")

    update: dict = {**state, "case": case, "review": result, "completed_steps": completed}

    # Store structured feedback if review requests revision
    if result.get("decision") == "revise" and result.get("review_feedback"):
        update["review_feedback"] = result["review_feedback"]

    return update


def routing_node(state: WorkflowState) -> WorkflowState:
    """Deterministic routing based on company knowledge pack rules."""
    from app.agents.tools import _company_knowledge_singleton

    case = state["case"]
    company_id = state.get("company_id", "mock_bank")

    # Fetch company-specific routing rules
    company_context = None
    try:
        svc = _company_knowledge_singleton(company_id)
        ctx = svc.build_company_context("")
        company_context = {"routing_candidates": ctx.routing_candidates}
    except Exception:
        logger.warning("Could not load company routing rules for %s, using defaults", company_id)

    destination = run_routing(
        case=case,
        classification=state["classification"],
        risk=state["risk_assessment"],
        root_cause_hypothesis=state.get("root_cause_hypothesis"),
        review_decision=state.get("review", {}).get("decision", "approve"),
        company_context=company_context,
    )

    case.routed_to = destination
    case.team_assignment = destination
    case.status = CaseStatus.ROUTED

    completed = list(state.get("completed_steps", []))
    completed.append("route")

    return {**state, "case": case, "routed_to": destination, "completed_steps": completed}


# ── Build the agentic graph ─────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    """Construct the hub-and-spoke agentic workflow.

    Architecture:
        intake → supervisor → {specialists} → supervisor → ... → END

    The supervisor node returns Command(goto=...) so LangGraph handles
    routing dynamically — no hardcoded conditional edges.
    """
    graph = StateGraph(WorkflowState)

    # Deterministic entry
    graph.add_node("intake", wrap_node("intake", intake_node))

    # Supervisor (the brain — routes via Command)
    graph.add_node("supervisor", wrap_supervisor_node(supervisor_node))

    # Specialist nodes (wrapped for observability)
    graph.add_node(_NODE_CLASSIFY, wrap_node("classify", classify_node))
    graph.add_node(_NODE_RISK, wrap_node("risk", risk_node))
    graph.add_node(_NODE_ROOT_CAUSE, wrap_node("root_cause", root_cause_node))
    graph.add_node(_NODE_RESOLVE, wrap_node("resolve", resolution_node))
    graph.add_node(_NODE_COMPLIANCE, wrap_node("check_compliance", compliance_node))
    graph.add_node(_NODE_REVIEW, wrap_node("qa_review", review_node))
    graph.add_node(_NODE_ROUTE, wrap_node("route", routing_node))

    # Entry: intake always runs first, then supervisor takes over
    graph.set_entry_point("intake")
    graph.add_edge("intake", "supervisor")

    # Every specialist returns to supervisor after completing
    for node_name in SPECIALIST_NODES:
        graph.add_edge(node_name, "supervisor")

    # Supervisor routes via Command(goto=...) — no conditional edges needed.
    # When supervisor returns Command(goto="__end__"), the graph terminates.

    return graph.compile()


# ── Convenience runner ───────────────────────────────────────────────────────

workflow = build_workflow()


def process_complaint(payload: dict) -> WorkflowState:
    """Run the full agentic complaint pipeline and return the final state."""
    setup_tracing()

    run_id = uuid.uuid4().hex
    company_id = payload.get("company_id") or "mock_bank"
    ar = ActiveRun(run_id=run_id, company_id=company_id)
    ctx_token = set_active_run(ar)
    tracer = get_workflow_tracer()

    initial_state: WorkflowState = {
        "raw_payload": payload,
        "retry_count": 0,
        "company_id": company_id,
    }

    invoke_config = {
        "run_name": f"complaint-{run_id}",
        "tags": [f"company_id:{company_id}", f"run_id:{run_id}"],
        "metadata": {
            "run_id": run_id,
            "company_id": company_id,
            "workflow_version": workflow_version(),
        },
    }

    final_state: WorkflowState | None = None
    try:
        with tracer.start_as_current_span("process_complaint") as root:
            tid = trace_id_hex_from_span(root)
            if tid:
                set_trace_id(tid)
            root.set_attribute("complaint.run_id", run_id)
            root.set_attribute("complaint.company_id", company_id)

            log_workflow_event(
                "workflow_started",
                run_id=run_id,
                company_id=company_id,
                trace_id=tid or "",
            )
            insert_workflow_run(run_id, company_id, tid or None)

            try:
                final_state = workflow.invoke(initial_state, config=invoke_config)
            except Exception as exc:
                root.record_exception(exc)
                root.set_status(Status(StatusCode.ERROR, str(exc)))
                log_workflow_event(
                    "workflow_failed",
                    run_id=run_id,
                    node_name="process_complaint",
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                )
                finalize_workflow_run(
                    run_id,
                    run_status="failed",
                    final_route=None,
                    final_severity=None,
                    manual_review_required=False,
                    retry_count_total=int(initial_state.get("retry_count") or 0),
                )
                raise

            root.set_status(Status(StatusCode.OK))

        assert final_state is not None
        status, route, sev, manual, retries = derive_run_outcome(final_state)
        finalize_workflow_run(
            run_id,
            run_status=status,
            final_route=route,
            final_severity=sev,
            manual_review_required=manual,
            retry_count_total=retries,
        )
        log_workflow_event(
            "workflow_completed",
            run_id=run_id,
            final_route=route,
            run_status=status,
            total_retry_count=retries,
        )
        logger.info("Workflow complete – routed to %s", final_state.get("routed_to"))
        return final_state
    finally:
        reset_active_run(ctx_token)
