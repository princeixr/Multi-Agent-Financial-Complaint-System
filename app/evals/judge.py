"""Rubric-based evaluator for benchmarked complaint-system outputs.

This judge is intentionally deterministic and auditable. It scores whether the
system output appears grounded, contradiction-aware, and complete based on the
benchmark case input and the generated workflow output.
"""

from __future__ import annotations

import re
from typing import Any


_AMOUNT_RE = re.compile(r"\$?\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b")


def _extract_amounts(text: str) -> list[float]:
    values: list[float] = []
    for match in _AMOUNT_RE.findall(text or ""):
        cleaned = match.replace("$", "").replace(",", "")
        try:
            values.append(float(cleaned))
        except ValueError:
            continue
    return values


def _collect_document_text(documents: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        for key in ("text", "content", "excerpt", "raw_text", "normalized_text"):
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())
    return "\n".join(chunks)


def run_rubric_judge(
    *,
    case_input: dict[str, Any],
    system_output: dict[str, Any],
) -> dict[str, Any]:
    """Return structured rubric output for one benchmark execution."""
    narrative = str(case_input.get("narrative") or "")
    documents = case_input.get("documents") or []
    document_text = _collect_document_text(documents if isinstance(documents, list) else [])

    classification = system_output.get("classification") or {}
    risk = system_output.get("risk") or system_output.get("risk_assessment") or {}
    resolution = system_output.get("resolution") or {}
    doc_consistency = system_output.get("document") or system_output.get("document_consistency") or {}

    narrative_amounts = _extract_amounts(narrative)
    document_amounts = _extract_amounts(document_text)
    contradiction_expected = bool(
        narrative_amounts
        and document_amounts
        and set(narrative_amounts) != set(document_amounts)
    )

    monetary_amount = resolution.get("monetary_amount")
    review_recommended = bool(classification.get("review_recommended"))
    confidence = classification.get("confidence")
    contradiction_flagged = str(doc_consistency.get("status") or "") == "contradiction"

    if contradiction_expected:
        contradiction_handled = contradiction_flagged or review_recommended
        confidence_calibrated = (
            review_recommended or (isinstance(confidence, (int, float)) and float(confidence) <= 0.65)
        )
        monetary_amount_grounded = (
            monetary_amount is None
            or monetary_amount in document_amounts
            or contradiction_flagged
        )
    else:
        contradiction_handled = True
        confidence_calibrated = True
        monetary_amount_grounded = True

    document_grounded = True
    if documents:
        document_grounded = contradiction_flagged or bool(doc_consistency) or review_recommended

    rubric = {
        "classification_present": bool(classification),
        "risk_present": bool(risk),
        "root_cause_present": bool(system_output.get("root_cause") or system_output.get("root_cause_hypothesis")),
        "resolution_present": bool(resolution),
        "document_grounded": document_grounded,
        "contradiction_handled": contradiction_handled,
        "monetary_amount_grounded": monetary_amount_grounded,
        "confidence_calibrated": confidence_calibrated,
    }

    failed_dimensions = [key for key, passed in rubric.items() if not passed]
    overall = "pass" if not failed_dimensions else "needs_review"
    if len(failed_dimensions) >= 3:
        overall = "fail"

    return {
        "judge_name": "rubric_judge",
        "judge_version": "v1",
        "overall_verdict": overall,
        "rubric": rubric,
        "summary": {
            "contradiction_expected": contradiction_expected,
            "narrative_amounts": narrative_amounts,
            "document_amounts": document_amounts,
            "failed_dimensions": failed_dimensions,
        },
    }
