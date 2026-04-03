"""LangGraph workflow that orchestrates all complaint‑processing agents."""

from __future__ import annotations

import json
import logging

from langgraph.graph import END, StateGraph

from app.agents.classification import run_classification
from app.agents.compliance import run_compliance_check
from app.agents.intake import run_intake
from app.agents.root_cause import run_root_cause_hypothesis
from app.agents.resolution import run_resolution
from app.agents.review import run_review
from app.agents.risk import run_risk_assessment
from app.agents.routing import run_routing
from app.knowledge import CompanyKnowledgeService
from app.orchestrator.rules import (
    low_confidence_gate,
    needs_compliance_review,
    review_decision_router,
)
from app.orchestrator.state import WorkflowState
from app.retrieval.complaint_index import ComplaintIndex
from app.retrieval.resolution_index import ResolutionIndex
from app.schemas.case import CaseCreate, CaseStatus
from app.schemas.evidence import EvidenceItem, EvidenceTrace
from app.schemas.root_cause import RootCauseHypothesis

logger = logging.getLogger(__name__)

# ── Lazy retrieval indices (avoid loading embedding models at import time) ──
_complaint_index: ComplaintIndex | None = None
_resolution_index: ResolutionIndex | None = None
_company_knowledge_by_id: dict[str, CompanyKnowledgeService] = {}


def _complaint_index_singleton() -> ComplaintIndex:
    global _complaint_index
    if _complaint_index is None:
        _complaint_index = ComplaintIndex()
    return _complaint_index


def _resolution_index_singleton() -> ResolutionIndex:
    global _resolution_index
    if _resolution_index is None:
        _resolution_index = ResolutionIndex()
    return _resolution_index


def _company_knowledge_singleton(company_id: str) -> CompanyKnowledgeService:
    if company_id not in _company_knowledge_by_id:
        _company_knowledge_by_id[company_id] = CompanyKnowledgeService(
            company_id=company_id
        )
    return _company_knowledge_by_id[company_id]


# ── Node functions ───────────────────────────────────────────────────────────

def intake_node(state: WorkflowState) -> WorkflowState:
    payload = CaseCreate(**state["raw_payload"])
    case = run_intake(payload)
    return {**state, "case": case}


def company_context_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    company_id = state["company_id"]

    company_knowledge = _company_knowledge_singleton(company_id)
    context = company_knowledge.build_company_context(case.consumer_narrative)

    # Evidence trace begins with the company knowledge slices we retrieved.
    evidence_trace = EvidenceTrace(
        items=[
            EvidenceItem(
                evidence_type="company_taxonomy_candidates",
                summary="Operational taxonomy slices selected for this narrative",
                source_ref=company_id,
                metadata=context.taxonomy_candidates,
            ),
            EvidenceItem(
                evidence_type="company_severity_candidates",
                summary="Company severity rubric snippets selected for this narrative",
                source_ref=company_id,
                metadata={"severity_candidates": context.severity_candidates},
            ),
            EvidenceItem(
                evidence_type="company_policy_candidates",
                summary="Company policy snippets selected for this narrative",
                source_ref=company_id,
                metadata={"policy_candidates": context.policy_candidates},
            ),
            EvidenceItem(
                evidence_type="company_root_cause_controls",
                summary="Control knowledge selected for root-cause inference",
                source_ref=company_id,
                metadata={"controls": context.root_cause_controls},
            ),
        ]
    )

    case.evidence_trace = evidence_trace.model_dump()
    return {
        **state,
        "company_context": {
            "company_id": company_id,
            "taxonomy_candidates": context.taxonomy_candidates,
            "severity_candidates": context.severity_candidates,
            "policy_candidates": context.policy_candidates,
            "routing_candidates": context.routing_candidates,
            "root_cause_controls": context.root_cause_controls,
        },
        "evidence_trace": evidence_trace,
        "case": case,
    }


def classify_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    retry = state.get("classification") is not None
    if retry:
        # Fix retry-counter progression: when we loop back to classification,
        # increment the counter so downstream gates can stop after MAX_RETRIES.
        state["retry_count"] = state.get("retry_count", 0) + 1  # type: ignore[misc]
    result = run_classification(
        narrative=case.consumer_narrative,
        product=case.product,
        sub_product=case.sub_product,
        company=case.company,
        state=case.state,
        complaint_index=_complaint_index_singleton(),
        company_context=state.get("company_context"),
    )
    case.classification = result.model_dump()
    case.status = CaseStatus.CLASSIFIED
    case.operational_mapping = {
        "product_category": result.product_category.value,
        "issue_type": result.issue_type.value,
        "sub_issue": result.sub_issue,
    }
    return {**state, "case": case, "classification": result}


def risk_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    result = run_risk_assessment(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        complaint_index=_complaint_index_singleton(),
        company_context=state.get("company_context"),
    )
    case.risk_assessment = result.model_dump()
    case.severity_class = result.risk_level.value
    case.status = CaseStatus.RISK_ASSESSED
    return {**state, "case": case, "risk_assessment": result}


def root_cause_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    company_context = state.get("company_context", {})

    result: RootCauseHypothesis = run_root_cause_hypothesis(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        risk=state["risk_assessment"],
        company_root_cause_controls=company_context.get("root_cause_controls", []),
        evidence_trace=state.get("evidence_trace"),
    )
    case.root_cause_hypothesis = result.model_dump()
    case.status = CaseStatus.RISK_ASSESSED  # root-cause doesn't change main stage enum yet
    return {**state, "case": case, "root_cause_hypothesis": result}


def resolution_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    if state.get("resolution") is not None:
        state["retry_count"] = state.get("retry_count", 0) + 1  # type: ignore[misc]
    result = run_resolution(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        risk=state["risk_assessment"],
        resolution_index=_resolution_index_singleton(),
        root_cause_hypothesis=state.get("root_cause_hypothesis"),
        company_context=state.get("company_context"),
    )
    case.proposed_resolution = result.model_dump()
    case.status = CaseStatus.RESOLUTION_PROPOSED
    return {**state, "case": case, "resolution": result}


def compliance_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    result = run_compliance_check(
        narrative=case.consumer_narrative,
        classification=state["classification"],
        risk=state["risk_assessment"],
        resolution=state["resolution"],
        company_context=state.get("company_context"),
    )
    case.compliance_flags = result.get("flags", [])
    case.evidence_trace = (
        state.get("evidence_trace").model_dump() if state.get("evidence_trace") else None
    )
    case.status = CaseStatus.COMPLIANCE_CHECKED
    return {**state, "case": case, "compliance": result}


def review_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    result = run_review(
        narrative=case.consumer_narrative,
        classification_json=json.dumps(state["classification"].model_dump()),
        risk_json=json.dumps(state["risk_assessment"].model_dump()),
        resolution_json=json.dumps(state["resolution"].model_dump()),
        compliance_json=json.dumps(state.get("compliance", {})),
    )
    case.review_notes = result.get("notes", "")
    case.status = CaseStatus.REVIEWED
    return {**state, "case": case, "review": result}


def routing_node(state: WorkflowState) -> WorkflowState:
    case = state["case"]
    destination = run_routing(
        case=case,
        classification=state["classification"],
        risk=state["risk_assessment"],
        root_cause_hypothesis=state.get("root_cause_hypothesis"),
        review_decision=state.get("review", {}).get("decision", "approve"),
        company_context=state.get("company_context"),
    )
    case.routed_to = destination
    case.team_assignment = destination
    case.status = CaseStatus.ROUTED
    return {**state, "case": case, "routed_to": destination}


# ── Conditional‑edge helpers (must return node names) ────────────────────────

def _confidence_router(state: WorkflowState) -> str:
    return low_confidence_gate(state)


def _compliance_router(state: WorkflowState) -> str:
    if needs_compliance_review(state):
        return "compliance"
    return "review"


def _review_router(state: WorkflowState) -> str:
    return review_decision_router(state)


# ── Build the graph ──────────────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    """Construct and return the compiled LangGraph workflow."""

    graph = StateGraph(WorkflowState)

    # Add nodes
    graph.add_node("intake", intake_node)
    graph.add_node("company_context", company_context_node)
    graph.add_node("classify", classify_node)
    graph.add_node("risk", risk_node)
    graph.add_node("root_cause", root_cause_node)
    graph.add_node("resolution", resolution_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("review", review_node)
    graph.add_node("route", routing_node)

    # Set entry point
    graph.set_entry_point("intake")

    # Linear edges
    graph.add_edge("intake", "company_context")
    graph.add_edge("company_context", "classify")

    # Conditional: after classification, check confidence
    graph.add_conditional_edges(
        "classify",
        _confidence_router,
        {"continue": "risk", "reclassify": "classify"},
    )

    graph.add_edge("risk", "root_cause")
    graph.add_edge("root_cause", "resolution")

    # Conditional: after resolution, decide if compliance check is needed
    graph.add_conditional_edges(
        "resolution",
        _compliance_router,
        {"compliance": "compliance", "review": "review"},
    )

    graph.add_edge("compliance", "review")

    # Conditional: after review, decide next step
    graph.add_conditional_edges(
        "review",
        _review_router,
        {"route": "route", "revise": "resolution", "escalate": "route"},
    )

    graph.add_edge("route", END)

    return graph.compile()


# ── Convenience runner ───────────────────────────────────────────────────────

workflow = build_workflow()


def process_complaint(payload: dict) -> WorkflowState:
    """Run the full complaint pipeline and return the final state."""
    initial_state: WorkflowState = {
        "raw_payload": payload,
        "retry_count": 0,
        "company_id": payload.get("company_id") or "mock_bank",
    }
    final_state = workflow.invoke(initial_state)
    logger.info("Workflow complete – routed to %s", final_state.get("routed_to"))
    return final_state
