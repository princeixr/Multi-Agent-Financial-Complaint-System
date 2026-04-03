from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .mock_company_pack import MockCompanyPack


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9_]+", text.lower()) if t}


def _score_by_cues(narrative: str, cues: Iterable[str]) -> float:
    """
    Tiny keyword-matching retriever used for the demo "company knowledge layer".

    This is intentionally lightweight: it keeps the platform runnable without
    requiring vector ingestion of enterprise knowledge packs.
    """

    tokens = _tokenize(narrative)
    cue_tokens = set()
    for c in cues:
        cue_tokens |= _tokenize(c)
    if not cue_tokens:
        return 0.0
    overlap = tokens & cue_tokens
    return len(overlap) / max(1, len(cue_tokens))


@dataclass(frozen=True)
class CompanyContext:
    company_id: str
    taxonomy_candidates: dict[str, Any]
    severity_candidates: list[dict[str, Any]]
    policy_candidates: list[dict[str, Any]]
    routing_candidates: dict[str, Any]
    root_cause_controls: list[dict[str, Any]]


class CompanyKnowledgeService:
    """
    Demo implementation of the "company knowledge layer".

    In this repo we simulate company knowledge via a pack that can be swapped
    per company_id. Retrieval is done via lightweight cue matching with an
    optional deterministic routing matrix.
    """

    def __init__(self, company_id: str | None = None) -> None:
        self.company_id = company_id or os.getenv("COMPANY_ID", MockCompanyPack.company_id)
        if self.company_id != MockCompanyPack.company_id:
            # For now, only the mock pack exists. Keep the interface stable.
            raise ValueError(
                f"Unknown company_id={self.company_id}. "
                "Only the demo mock pack is available in this repository."
            )

        self._pack = MockCompanyPack()

    def build_company_context(self, narrative: str) -> CompanyContext:
        product_categories = self._pack.operational_taxonomy["product_categories"]
        issue_types = self._pack.operational_taxonomy["issue_types"]

        # Retrieve a small slice of taxonomy candidates most relevant to the narrative.
        top_products = sorted(
            product_categories,
            key=lambda x: _score_by_cues(narrative, x.get("cues", [])),
            reverse=True,
        )[:3]
        top_issues = sorted(
            issue_types,
            key=lambda x: _score_by_cues(narrative, x.get("cues", [])),
            reverse=True,
        )[:5]

        top_severity = sorted(
            self._pack.severity_rubric,
            key=lambda x: _score_by_cues(narrative, x.get("cues", [])),
            reverse=True,
        )[:3]

        top_policies = sorted(
            self._pack.policy_snippets,
            key=lambda x: _score_by_cues(narrative, x.get("cues", [])),
            reverse=True,
        )[:3]

        return CompanyContext(
            company_id=self.company_id,
            taxonomy_candidates={
                "product_categories": top_products,
                "issue_types": top_issues,
            },
            severity_candidates=top_severity,
            policy_candidates=top_policies,
            routing_candidates=self._pack.routing_matrix,
            root_cause_controls=sorted(
                self._pack.root_cause_controls,
                key=lambda x: _score_by_cues(narrative, x.get("cues", [])),
                reverse=True,
            )[:3],
        )

