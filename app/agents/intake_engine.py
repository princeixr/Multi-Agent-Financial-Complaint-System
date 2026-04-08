"""Channel-agnostic intake engine used by chat (and later voice).

The engine maintains an IntakeSessionState and, on each turn:
  * calls an LLM with the existing IntakePacket and latest user message
  * parses a JSON response with `assistant_message` and updated `intake_packet`
  * applies deterministic sufficiency rules and builds a CaseCreate-compatible payload
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Dict, Tuple
from uuid import uuid4

from app.agents.llm_factory import create_llm
from app.agents.llm_json import parse_llm_json
from app.schemas.case import CaseCreate
from app.schemas.intake import (
    InformationSufficiency,
    IntakePacket,
    IntakeSessionState,
    RecommendedHandoff,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "intake_chat.md"

# In-memory session store for the demo. For production, back this with Redis or DB.
_SESSIONS: Dict[str, IntakeSessionState] = {}


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


def _trace_intake_to_langsmith_enabled() -> bool:
    """Opt-in only: do not send raw intake chat history by default."""
    return _truthy_env("TRACE_INTAKE_TO_LANGSMITH")


class _temp_disable_langsmith_tracing:
    """Disable LangSmith tracing for intake turns without mutating env vars."""

    def __init__(self) -> None:
        self._ctx = None

    def __enter__(self):
        try:
            from langsmith.run_helpers import tracing_context  # type: ignore

            self._ctx = tracing_context(enabled=False)
            self._ctx.__enter__()
        except Exception:
            self._ctx = None

    def __exit__(self, exc_type, exc, tb):
        if self._ctx is not None:
            self._ctx.__exit__(exc_type, exc, tb)


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _compute_sufficiency(packet: IntakePacket) -> IntakePacket:
    """Deterministic sufficiency rules aligned with CaseCreate validation.

    For MVP we keep this intentionally simple:
      * require a financial complaint intent
      * require narrative_for_case length >= 10 characters
    """
    missing: list[str] = []

    if not packet.is_financial_complaint or not packet.supported_by_platform:
        packet.information_sufficiency = InformationSufficiency.INSUFFICIENT
        packet.recommended_handoff = RecommendedHandoff.UNSUPPORTED
        packet.missing_fields = ["financial_domain"]
        return packet

    if len((packet.narrative_for_case or "").strip()) < 10:
        missing.append("narrative_for_case")

    if missing:
        packet.information_sufficiency = InformationSufficiency.INSUFFICIENT
    else:
        packet.information_sufficiency = InformationSufficiency.SUFFICIENT

    # For now we always recommend supervisor when sufficient.
    packet.recommended_handoff = (
        RecommendedHandoff.SUPERVISOR
        if packet.information_sufficiency is InformationSufficiency.SUFFICIENT
        else RecommendedHandoff.SUPERVISOR
    )
    packet.missing_fields = missing
    return packet


def _build_case_payload(packet: IntakePacket, company_id: str | None) -> dict:
    """Construct a CaseCreate-compatible payload from an IntakePacket."""
    narrative = (packet.narrative_for_case or "").strip()
    data = {
        "company_id": company_id,
        "consumer_narrative": narrative or None,
        # product/sub_product are hints only; classification will do proper mapping.
        "product": packet.product_hint,
        "sub_product": packet.sub_issue_hint or packet.issue_hint,
        "company": None,
        "state": None,
        "zip_code": None,
        "channel": "web",
        "submitted_at": None,
        "external_product_category": packet.product_hint,
        "external_issue_type": packet.issue_hint,
        "requested_resolution": packet.desired_resolution,
        # CFPB portal fields are optional in this path.
        "cfpb_product": None,
        "cfpb_sub_product": None,
        "cfpb_issue": None,
        "cfpb_sub_issue": None,
    }
    return data


def start_intake_session(channel: str = "web_chat", company_id: str | None = None) -> Tuple[str, IntakeSessionState]:
    """Create a new intake session with an initial greeting from the agent."""
    session_id = uuid4().hex
    packet = IntakePacket(channel=channel if channel in ("web_chat", "voice") else "web_chat", company_id=company_id)
    state = IntakeSessionState(
        session_id=session_id,
        channel=packet.channel,
        company_id=company_id,
        packet=packet,
        turn_index=0,
        last_agent_message="",
        last_user_message="",
        completed=False,
        handoff_triggered=False,
    )
    greeting = (
        "Thanks for reaching out. I'm the virtual intake assistant for complaints. "
        "Please briefly describe what happened and which financial product or service it relates to."
    )
    state.last_agent_message = greeting
    _SESSIONS[session_id] = state
    return session_id, state


def get_intake_session(session_id: str) -> IntakeSessionState | None:
    return _SESSIONS.get(session_id)


def process_intake_message(session_id: str, user_message: str, model_name: str | None = None) -> IntakeSessionState:
    """Process one user turn and update the intake session state."""
    state = _SESSIONS.get(session_id)
    if state is None:
        raise KeyError(f"Unknown intake session_id={session_id}")

    state.turn_index += 1
    state.last_user_message = user_message

    system_prompt = _load_prompt()
    llm = create_llm(model_name=model_name, temperature=0.0)

    # We send the current packet and latest user message; the model returns
    # assistant_message + a full updated intake_packet object.
    payload = {
        "current_intake_packet": json.loads(state.packet.model_dump_json()),
        "last_user_message": user_message,
    }
    user_content = json.dumps(payload, ensure_ascii=False)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # Privacy default: do not emit intake turns to LangSmith unless explicitly enabled.
    if _trace_intake_to_langsmith_enabled():
        response = llm.invoke(messages)
    else:
        with _temp_disable_langsmith_tracing():
            response = llm.invoke(messages)
    raw = getattr(response, "content", None)
    data = parse_llm_json(raw)

    assistant_message = data.get("assistant_message") or ""
    packet_data = data.get("intake_packet") or {}

    # Merge: start from previous packet and overlay fields from model.
    merged = state.packet.model_copy(update=packet_data)
    merged = _compute_sufficiency(merged)

    # Build CaseCreate-compatible snapshot if sufficient (may still be useful when partial).
    merged.intake_case = _build_case_payload(merged, state.company_id)

    state.packet = merged
    state.last_agent_message = assistant_message

    # Mark completed when we have sufficient information; handoff itself is triggered
    # by the API layer when it calls finalize_intake_session.
    if merged.information_sufficiency is InformationSufficiency.SUFFICIENT:
        state.completed = True

    _SESSIONS[session_id] = state
    return state


def finalize_intake_session(session_id: str) -> Tuple[CaseCreate, IntakeSessionState]:
    """Build a CaseCreate from the intake session; caller is responsible for running the workflow.

    Raises:
        ValueError if information is not sufficient.
    """
    state = _SESSIONS.get(session_id)
    if state is None:
        raise KeyError(f"Unknown intake session_id={session_id}")

    packet = state.packet
    packet = _compute_sufficiency(packet)
    if packet.information_sufficiency is not InformationSufficiency.SUFFICIENT:
        raise ValueError(
            f"Intake information is not sufficient to open a case; missing={packet.missing_fields}"
        )

    payload = _build_case_payload(packet, state.company_id)
    case_create = CaseCreate(**payload)
    state.packet.intake_case = payload
    state.completed = True
    state.handoff_triggered = True
    _SESSIONS[session_id] = state
    return case_create, state

