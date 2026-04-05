"""Classification agent – assigns product category and issue type."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from app.agents.llm_factory import create_llm
from app.agents.llm_json import parse_llm_json
from app.retrieval.complaint_index import ComplaintIndex
from app.schemas.classification import ClassificationResult

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classification.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def run_classification(
    narrative: str,
    product: str | None = None,
    sub_product: str | None = None,
    company: str | None = None,
    state: str | None = None,
    complaint_index: ComplaintIndex | None = None,
    company_context: dict | None = None,
    model_name: str | None = None,
    temperature: float = 0.0,
) -> ClassificationResult:
    """Classify the complaint and return a structured result.

    Optionally retrieves similar complaints to provide few‑shot context.
    """
    logger.info("Classification agent running")

    # Retrieve similar complaints for context (RAG)
    similar_context = ""
    if complaint_index is not None:
        similar_docs = complaint_index.search(narrative, k=3)
        if similar_docs:
            similar_context = "\n---\n".join(doc.page_content for doc in similar_docs)

    if company_context is None:
        # Evaluation harnesses and standalone runs may not pass company_context.
        # Fall back to the demo mock pack so the prompt always has candidates.
        from app.knowledge import CompanyKnowledgeService

        ctx = CompanyKnowledgeService().build_company_context(narrative)
        company_context = {
            "taxonomy_candidates": ctx.taxonomy_candidates,
            "company_id": ctx.company_id,
        }

    taxonomy_snippet = ""
    if company_context:
        candidates = company_context.get("taxonomy_candidates", {})
        prod_candidates = candidates.get("product_categories", [])
        issue_candidates = candidates.get("issue_types", [])

        if prod_candidates or issue_candidates:
            taxonomy_snippet = (
                "Company operational taxonomy candidates:\n"
                f"Product candidates: {prod_candidates}\n"
                f"Issue candidates: {issue_candidates}\n"
            )

    system_prompt = _load_prompt()

    user_message = (
        f"Narrative: {narrative}\n"
        f"Product (if provided): {product or 'N/A'}\n"
        f"Sub‑product (if provided): {sub_product or 'N/A'}\n"
        f"Company: {company or 'N/A'}\n"
        f"State: {state or 'N/A'}\n"
    )
    if similar_context:
        user_message += f"\nSimilar complaints for reference:\n{similar_context}\n"
    if taxonomy_snippet:
        user_message += f"\n{taxonomy_snippet}\n"

    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{input}")]
    )

    llm = create_llm(model_name=model_name, temperature=temperature)
    chain = prompt | llm

    response = chain.invoke({"input": user_message})
    result_data = parse_llm_json(getattr(response, "content", None))

    result = ClassificationResult(**result_data)
    logger.info(
        "Classification complete – category=%s, confidence=%.2f",
        result.product_category,
        result.confidence,
    )
    return result
