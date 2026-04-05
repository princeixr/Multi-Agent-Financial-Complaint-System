"""Risk‑assessment agent – evaluates complaint risk level."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from app.agents.llm_factory import create_llm
from app.agents.llm_json import parse_llm_json
from app.retrieval.complaint_index import ComplaintIndex
from app.schemas.classification import ClassificationResult
from app.schemas.risk import RiskAssessment

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "risk.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def run_risk_assessment(
    narrative: str,
    classification: ClassificationResult,
    complaint_index: ComplaintIndex | None = None,
    company_context: dict | None = None,
    model_name: str | None = None,
    temperature: float = 0.0,
) -> RiskAssessment:
    """Assess the risk posed by the complaint."""
    logger.info("Risk agent running")

    similar_context = ""
    if complaint_index is not None:
        similar_docs = complaint_index.search(narrative, k=3)
        if similar_docs:
            similar_context = "\n---\n".join(doc.page_content for doc in similar_docs)

    system_prompt = _load_prompt()

    severity_snippet = ""
    if company_context:
        severity_candidates = company_context.get("severity_candidates", [])
        policy_snippets = company_context.get("policy_candidates", [])
        if severity_candidates or policy_snippets:
            severity_snippet = (
                "Company severity rubric candidates:\n"
                f"{severity_candidates}\n"
                "Company policy candidates relevant to this case:\n"
                f"{policy_snippets}\n"
            )

    user_message = (
        f"Narrative: {narrative}\n"
        f"Classification: {classification.model_dump_json()}\n"
        f"Similar complaints context: {similar_context or 'None available'}\n"
        f"{severity_snippet}"
    )

    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{input}")]
    )

    llm = create_llm(model_name=model_name, temperature=temperature)
    chain = prompt | llm

    response = chain.invoke({"input": user_message})
    result_data = parse_llm_json(getattr(response, "content", None))

    result = RiskAssessment(**result_data)
    logger.info(
        "Risk assessment complete – level=%s, score=%.1f",
        result.risk_level,
        result.risk_score,
    )
    return result
