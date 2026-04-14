import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.classification import run_classification
from app.schemas.case import CaseRead


class ClassificationPipelineTests(unittest.TestCase):
    def test_trivial_case_skips_tool_loop(self) -> None:
        case = CaseRead(
            consumer_narrative="",
            cfpb_product="Credit card",
            cfpb_issue="Billing dispute",
        )

        class FakeLLM:
            def invoke(self, messages):
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "product_category": "credit_card",
                            "issue_type": "billing_disputes",
                            "sub_issue": None,
                            "confidence": 0.73,
                            "reasoning": "Structured intake fields point to a credit card billing dispute.",
                            "keywords": ["credit card", "billing dispute"],
                            "review_recommended": False,
                            "reason_codes": [],
                            "alternate_candidates": [],
                        }
                    )
                )

        with patch("app.agents.classification.create_llm", return_value=FakeLLM()), patch(
            "app.agents.classification.run_agent_with_tools",
            side_effect=AssertionError("tool loop should not run for trivial cases"),
        ):
            out = run_classification(case=case)

        self.assertEqual(out.result.product_category.value, "credit_card")
        self.assertEqual(out.audit.evidence_used, {})
        self.assertTrue(out.audit.assess_skipped_llm)
        self.assertFalse(out.audit.plan["needs_retrieval"])

    def test_ambiguous_case_uses_tool_loop(self) -> None:
        case = CaseRead(
            consumer_narrative="My account was frozen and then I also saw an unauthorized transfer.",
            product="Checking account",
            cfpb_product="Checking or savings account",
            cfpb_issue="Managing an account",
        )

        assess = {
            "complexity": "ambiguous",
            "narrative_status": "present",
            "structured_field_completeness": "partial",
            "consistency": "partial_conflict",
            "conflict_score": 0.6,
            "recommended_weighting": "narrative",
            "rationale": "Narrative suggests overlapping access and fraud problems.",
        }

        result = {
            "product_category": "checking_savings",
            "issue_type": "fraud_or_scam",
            "sub_issue": "unauthorized_transaction",
            "confidence": 0.61,
            "reasoning": "Narrative and retrieval indicate the primary issue is an unauthorized transfer.",
            "keywords": ["account frozen", "unauthorized transfer"],
            "review_recommended": True,
            "reason_codes": ["retrieval_used"],
            "alternate_candidates": [],
        }

        class FakeLLM:
            def invoke(self, messages):
                return SimpleNamespace(content=json.dumps(assess))

        with patch("app.agents.classification.create_llm", return_value=FakeLLM()), patch(
            "app.agents.classification.run_agent_with_tools",
            return_value=(result, {"search_similar_complaints": True, "lookup_company_taxonomy": True}),
        ) as tool_loop:
            out = run_classification(case=case)

        self.assertTrue(tool_loop.called)
        self.assertTrue(out.audit.plan["needs_retrieval"])
        self.assertIn("search_similar_complaints", out.audit.evidence_used)


if __name__ == "__main__":
    unittest.main()
