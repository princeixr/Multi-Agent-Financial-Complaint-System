"""Compliance agent – checks for regulatory and policy violations."""

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.schemas.classification import ClassificationResult
from app.schemas.resolution import ResolutionRecommendation
from app.schemas.risk import RiskAssessment

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a compliance officer reviewing a consumer complaint case that has
already been classified, risk‑assessed, and assigned a proposed resolution.

Your job is to flag any **regulatory or policy compliance concerns**.

Ground your review in the **company policy candidates** and compliance guidance
provided in the user message. You may consider well-known consumer-protection
themes (non-exhaustive examples: fair credit reporting, debt collection
communications, disclosures/notice adequacy, unfair/deceptive/abusive acts),
but do not invent company-specific rules not present in the retrieved guidance.

Return a JSON object:
{
  "flags": ["<flag_1>", "<flag_2>", ...],
  "passed": true/false,
  "notes": "<optional free‑text note>"
}

If no concerns exist, return `{"flags": [], "passed": true, "notes": null}`.
"""


def run_compliance_check(
    narrative: str,
    classification: ClassificationResult,
    risk: RiskAssessment,
    resolution: ResolutionRecommendation,
    company_context: dict | None = None,
    model_name: str = "gpt-4o",
    temperature: float = 0.0,
) -> dict:
    """Run the compliance check and return flags."""
    logger.info("Compliance agent running")

    policy_snippet = ""
    if company_context:
        policy_candidates = company_context.get("policy_candidates", [])
        if policy_candidates:
            policy_snippet = (
                "Company policy candidates relevant to compliance review:\n"
                f"{policy_candidates}\n"
            )

    user_message = (
        f"Narrative: {narrative}\n"
        f"Classification: {classification.model_dump_json()}\n"
        f"Risk Assessment: {risk.model_dump_json()}\n"
        f"Proposed Resolution: {resolution.model_dump_json()}\n"
        f"{policy_snippet}"
    )

    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_PROMPT), ("human", "{input}")]
    )

    llm = ChatOpenAI(model=model_name, temperature=temperature)
    chain = prompt | llm

    response = chain.invoke({"input": user_message})
    result = json.loads(response.content)

    logger.info(
        "Compliance check complete – passed=%s, flags=%d",
        result.get("passed"),
        len(result.get("flags", [])),
    )
    return result
