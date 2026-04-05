from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agents.llm_factory import create_llm
from app.agents.llm_json import parse_llm_json
from langchain_core.prompts import ChatPromptTemplate

from app.schemas.classification import ClassificationResult
from app.schemas.evidence import EvidenceTrace
from app.schemas.root_cause import RootCauseHypothesis
from app.schemas.risk import RiskAssessment

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are a root-cause analyst for a consumer-complaint operations pipeline.

You will be given:
- the complaint narrative and any extracted complaint facts
- the company-aware operational classification
- the company-aware risk assessment
- retrieved company control knowledge (how internal failures typically arise)
- an evidence trace describing what information you should ground on

Return a JSON object matching the RootCauseHypothesis schema:
{{
  "root_cause_category": "<string>",
  "confidence": <0.0..1.0>,
  "reasoning": "<brief explanation grounded in evidence>",
  "controls_to_check": ["<control_1>", ...],
  "notes": "<optional notes>"
}}

Rules:
- Prefer grounding in provided control knowledge and evidence trace.
- If uncertainty remains, use lower confidence and suggest controls_to_check that can validate the hypothesis.
"""


def run_root_cause_hypothesis(
    narrative: str,
    classification: ClassificationResult,
    risk: RiskAssessment,
    company_root_cause_controls: list[dict],
    evidence_trace: EvidenceTrace | None = None,
    model_name: str | None = None,
    temperature: float = 0.0,
) -> RootCauseHypothesis:
    logger.info("Root-cause agent running")

    controls_text = "\n---\n".join(
        json.dumps(c, ensure_ascii=False) for c in company_root_cause_controls
    )

    evidence_text = evidence_trace.model_dump_json() if evidence_trace else "{}"

    user_message = (
        f"Narrative: {narrative}\n"
        f"Operational classification: {classification.model_dump_json()}\n"
        f"Risk assessment: {risk.model_dump_json()}\n"
        f"Company control knowledge candidates:\n{controls_text}\n"
        f"Evidence trace (what to ground on): {evidence_text}\n"
    )

    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_PROMPT), ("human", "{input}")]
    )
    llm = create_llm(model_name=model_name, temperature=temperature)
    chain = prompt | llm

    response = chain.invoke({"input": user_message})
    result_data = parse_llm_json(getattr(response, "content", None))
    result = RootCauseHypothesis(**result_data)

    logger.info(
        "Root-cause complete – category=%s, confidence=%.2f",
        result.root_cause_category,
        result.confidence,
    )
    return result
