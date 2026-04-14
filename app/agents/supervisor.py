"""Supervisor agent — decides which specialist to invoke next.

The supervisor reads the current WorkflowState, reasons about what has been
accomplished and what remains, and returns a LangGraph ``Command`` directing
the graph to the next specialist node.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.prompts import ChatPromptTemplate
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from app.agents.llm_factory import create_llm
from app.agents.llm_json import parse_llm_json

if TYPE_CHECKING:
    from app.orchestrator.state import WorkflowState

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "supervisor.md"

_VALID_AGENTS = frozenset(
    {"classify", "risk", "root_cause", "resolve", "check_compliance", "qa_review", "route", "FINISH"}
)

DEFAULT_MAX_STEPS = 15
MAX_AGENT_INVOCATIONS = 3


# ── Supervisor decision schema ──────────────────────────────────────────────

class SupervisorDecision(BaseModel):
    next_agent: Literal[
        "classify", "risk", "root_cause", "resolve",
        "check_compliance", "qa_review", "route", "FINISH",
    ]
    reasoning: str
    instructions: str = ""


# ── State summariser ────────────────────────────────────────────────────────

def _build_state_summary(state: dict[str, Any]) -> str:
    """Build a concise text summary of the current workflow state for the supervisor."""
    parts: list[str] = []

    # Case info
    case = state.get("case")
    if case:
        narrative = getattr(case, "consumer_narrative", None) or ""
        parts.append(f"Case narrative (first 300 chars): {narrative[:300]}")
        if len(narrative.strip()) < 10:
            parts.append(
                "Consumer narrative is absent or short — specialists use portal fields "
                "and classification; do not assume rich free-text detail."
            )
        parts.append(f"Product hint: {getattr(case, 'product', None) or 'N/A'}")
    else:
        parts.append("Case: not yet ingested")

    # Completed steps
    completed = state.get("completed_steps", [])
    parts.append(f"Completed steps: {completed if completed else 'none'}")
    parts.append(f"Step count: {state.get('step_count', 0)}/{state.get('max_steps', DEFAULT_MAX_STEPS)}")

    # Classification
    cls = state.get("classification")
    if cls:
        cat = getattr(cls, "product_category", None)
        cat_val = getattr(cat, "value", str(cat)) if cat else "N/A"
        issue = getattr(cls, "issue_type", None)
        issue_val = getattr(issue, "value", str(issue)) if issue else "N/A"
        conf = getattr(cls, "confidence", None)
        parts.append(
            f"Classification: product={cat_val}, issue={issue_val}, "
            f"confidence={conf:.2f}" if conf is not None else f"Classification: product={cat_val}, issue={issue_val}"
        )
        rr = getattr(cls, "review_recommended", False)
        if rr:
            rc = getattr(cls, "reason_codes", []) or []
            parts.append(
                f"Classification review_recommended=true; reason_codes={list(rc)}"
            )

    # Risk
    risk = state.get("risk_assessment")
    if risk:
        level = getattr(risk, "risk_level", None)
        level_val = getattr(level, "value", str(level)) if level else "N/A"
        score = getattr(risk, "risk_score", None)
        reg = getattr(risk, "regulatory_risk", None)
        parts.append(
            f"Risk: level={level_val}, score={score}, regulatory_risk={reg}"
        )

    # Root cause
    rc = state.get("root_cause_hypothesis")
    if rc:
        cat = getattr(rc, "root_cause_category", None)
        conf = getattr(rc, "confidence", None)
        parts.append(f"Root cause: {cat} (confidence={conf})")

    # Resolution
    res = state.get("resolution")
    if res:
        action = getattr(res, "recommended_action", None)
        action_val = getattr(action, "value", str(action)) if action else "N/A"
        conf = getattr(res, "confidence", None)
        parts.append(f"Resolution: action={action_val}, confidence={conf}")

    # Compliance
    comp = state.get("compliance")
    if comp:
        parts.append(
            f"Compliance: passed={comp.get('passed')}, flags={comp.get('flags', [])}"
        )

    # Review
    rev = state.get("review")
    if rev:
        parts.append(f"Review: decision={rev.get('decision')}, notes={rev.get('notes', '')}")

    # Review feedback (if review requested revision)
    feedback = state.get("review_feedback")
    if feedback:
        parts.append(f"Review feedback: {feedback}")

    # Routing
    routed = state.get("routed_to")
    if routed:
        parts.append(f"Routed to: {routed}")

    return "\n".join(parts)


# ── Safe fallback ───────────────────────────────────────────────────────────

def _fallback_command(
    state: dict[str, Any],
    error: Exception,
    step_count: int,
) -> Command:
    """Return a safe fallback Command when supervisor parsing/validation fails."""
    completed = state.get("completed_steps", [])
    fallback_agent = "route" if "route" not in completed else "__end__"

    logger.error(
        "Supervisor failed to parse LLM response (%s: %s); falling back to %s",
        type(error).__name__,
        str(error)[:300],
        fallback_agent,
    )

    update = {
        "step_count": step_count + 1,
        "supervisor_reasoning": f"Fallback: LLM response parsing failed ({type(error).__name__})",
        "supervisor_instructions": "",
    }

    if fallback_agent == "__end__":
        return Command(goto="__end__", update=update)

    return Command(goto=fallback_agent, update=update)


# ── Supervisor runner ───────────────────────────────────────────────────────

def run_supervisor(state: dict[str, Any]) -> Command:
    """Decide the next specialist agent to invoke.

    Returns a LangGraph ``Command`` with ``goto`` set to the chosen agent
    and ``update`` containing supervisor metadata for the state.
    """
    step_count = state.get("step_count", 0)
    max_steps = state.get("max_steps", DEFAULT_MAX_STEPS)
    completed_steps = list(state.get("completed_steps", []))

    # Safety: force finish if we've hit the step limit
    if step_count >= max_steps:
        logger.warning("Supervisor hit max_steps (%d), forcing route/FINISH", max_steps)
        if "route" not in completed_steps:
            return Command(
                goto="route",
                update={
                    "step_count": step_count + 1,
                    "supervisor_reasoning": "Max steps reached, forcing route.",
                    "supervisor_instructions": "",
                },
            )
        return Command(
            goto="__end__",
            update={
                "step_count": step_count + 1,
                "supervisor_reasoning": "Max steps reached, all done.",
                "supervisor_instructions": "",
            },
        )

    # Build prompt
    system_prompt = _PROMPT_PATH.read_text()
    state_summary = _build_state_summary(state)

    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{state_summary}")]
    )

    llm = create_llm()
    chain = prompt | llm

    response = chain.invoke({"state_summary": state_summary})

    try:
        result = parse_llm_json(getattr(response, "content", None))
        decision = SupervisorDecision(**result)
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        return _fallback_command(state, exc, step_count)

    logger.info(
        "Supervisor decision: next=%s, reasoning=%s",
        decision.next_agent,
        decision.reasoning,
    )

    # Handle FINISH
    if decision.next_agent == "FINISH":
        return Command(
            goto="__end__",
            update={
                "step_count": step_count + 1,
                "supervisor_reasoning": decision.reasoning,
                "supervisor_instructions": decision.instructions,
            },
        )

    # Validate the decision
    if decision.next_agent not in _VALID_AGENTS:
        logger.error("Supervisor returned invalid agent: %s, defaulting to route", decision.next_agent)
        decision.next_agent = "route"

    # Enforce max invocations per agent (prevent looping)
    agent_counts = Counter(completed_steps)
    if agent_counts[decision.next_agent] >= MAX_AGENT_INVOCATIONS:
        logger.warning(
            "Agent %s already invoked %d times (max %d), forcing route/FINISH",
            decision.next_agent,
            agent_counts[decision.next_agent],
            MAX_AGENT_INVOCATIONS,
        )
        if "route" not in completed_steps:
            decision.next_agent = "route"
        else:
            return Command(
                goto="__end__",
                update={
                    "step_count": step_count + 1,
                    "supervisor_reasoning": f"Agent {decision.next_agent} hit max invocations, ending workflow.",
                    "supervisor_instructions": "",
                },
            )

    return Command(
        goto=decision.next_agent,
        update={
            "step_count": step_count + 1,
            "supervisor_reasoning": decision.reasoning,
            "supervisor_instructions": decision.instructions,
        },
    )
