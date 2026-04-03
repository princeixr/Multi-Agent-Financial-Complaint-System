"""Resolution agent – recommends a resolution based on precedent."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.retrieval.resolution_index import ResolutionIndex
from app.schemas.classification import ClassificationResult
from app.schemas.resolution import ResolutionRecommendation
from app.schemas.risk import RiskAssessment

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "resolution.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def run_resolution(
    narrative: str,
    classification: ClassificationResult,
    risk: RiskAssessment,
    resolution_index: ResolutionIndex | None = None,
    root_cause_hypothesis: object | None = None,
    company_context: dict | None = None,
    model_name: str = "gpt-4o",
    temperature: float = 0.0,
) -> ResolutionRecommendation:
    """Propose a resolution for the complaint."""
    logger.info("Resolution agent running")

    similar_resolutions = ""
    if resolution_index is not None:
        similar_docs = resolution_index.search(narrative, k=3)
        if similar_docs:
            similar_resolutions = "\n---\n".join(doc.page_content for doc in similar_docs)

    system_prompt = _load_prompt()

    policy_snippet = ""
    if company_context:
        policy_candidates = company_context.get("policy_candidates", [])
        routing_candidates = company_context.get("routing_candidates", {})
        policy_snippet = (
            "Company policy candidates relevant to the resolution:\n"
            f"{policy_candidates}\n\n"
            "Company routing/ownership candidates (may influence remediation steps):\n"
            f"{routing_candidates}\n"
        )

    user_message = (
        f"Narrative: {narrative}\n"
        f"Classification: {classification.model_dump_json()}\n"
        f"Risk Assessment: {risk.model_dump_json()}\n"
        f"Similar resolutions: {similar_resolutions or 'None available'}\n"
        f"{policy_snippet}\n"
    )

    if root_cause_hypothesis is not None:
        user_message += (
            f"Root-cause hypothesis (grounding context): {root_cause_hypothesis}\n"
        )

    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{input}")]
    )

    llm = ChatOpenAI(model=model_name, temperature=temperature)
    chain = prompt | llm

    response = chain.invoke({"input": user_message})
    result_data = json.loads(response.content)

    result = ResolutionRecommendation(**result_data)
    logger.info(
        "Resolution complete – action=%s, confidence=%.2f",
        result.recommended_action,
        result.confidence,
    )
    return result
