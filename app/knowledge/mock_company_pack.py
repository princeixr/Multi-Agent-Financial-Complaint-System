from __future__ import annotations

# A simulated "company knowledge pack" used for this demo repository.
# In a real multi-company deployment, this pack would be replaced per company.

MOCK_COMPANY_ID = "mock_bank"

# Operational taxonomy for the demo company.
# The goal is to map external complaint concepts into internal operational labels.
#
# Note: these labels intentionally mirror the existing schema enums so the
# platform can evolve without needing a full taxonomy migration immediately.
OPERATIONAL_TAXONOMY = {
    "product_categories": [
        {
            "product_category": "credit_card",
            "definition": "Complaints related to credit cards, card fees, disputes, and card security holds.",
            "cues": ["credit card", "card", "charge", "purchase", "statement", "APR", "interest"],
        },
        {
            "product_category": "checking_savings",
            "definition": "Complaints related to deposit accounts, transfers, holds on funds, and access restrictions.",
            "cues": ["checking", "savings", "debit card", "funds access", "transfer", "ACH", "routing number"],
        },
        {
            "product_category": "debt_collection",
            "definition": "Complaints about debt collection practices, communications, and account handling by collectors.",
            "cues": ["debt", "collector", "collection", "dunning", "harass", "communication", "calls"],
        },
        {
            "product_category": "mortgage",
            "definition": "Complaints related to mortgage servicing, escrow, modifications, and foreclosure interactions.",
            "cues": ["mortgage", "servicing", "escrow", "foreclosure", "modification", "payment", "loan"],
        },
        {
            "product_category": "credit_reporting",
            "definition": "Complaints about credit reports, inaccuracies, disputes, and reporting timelines.",
            "cues": ["credit report", "credit bureau", "dispute", "incorrect information", "report"],
        },
        {
            "product_category": "student_loan",
            "definition": "Complaints related to student loan servicing, repayment changes, and billing processing.",
            "cues": ["student loan", "servicing", "repayment", "payment", "billing"],
        },
        {
            "product_category": "vehicle_loan",
            "definition": "Complaints for auto loans and related servicing, payoff statements, or payment processing.",
            "cues": ["auto loan", "vehicle loan", "payoff", "title", "loan payment", "servicing"],
        },
        {
            "product_category": "payday_loan",
            "definition": "Complaints about payday loans, short-term borrowing terms, and related servicing.",
            "cues": ["payday", "short-term", "installment", "loan terms"],
        },
        {
            "product_category": "money_transfer",
            "definition": "Complaints related to money transfers, remittances, and payment processing failures.",
            "cues": ["wire", "transfer", "remittance", "international", "payment processing", "transaction"],
        },
        {
            "product_category": "prepaid_card",
            "definition": "Complaints regarding prepaid cards, loading issues, fees, and access restrictions.",
            "cues": ["prepaid", "card", "load", "balance", "fees"],
        },
        {
            "product_category": "other",
            "definition": "Complaints that do not clearly fall into other product categories.",
            "cues": ["other", "unknown", "miscellaneous"],
        },
    ],
    "issue_types": [
        {
            "issue_type": "billing_disputes",
            "definition": "Complaints involving billing errors, duplicate charges, fee disputes, or incorrect account amounts.",
            "cues": ["charged twice", "duplicate", "fee", "billing", "amount", "refund", "overcharged"],
        },
        {
            "issue_type": "payment_processing",
            "definition": "Complaints where payments are not applied correctly or processing fails, causing account/payment issues.",
            "cues": ["payment not applied", "processing", "declined", "reversed", "returned payment", "misapplied"],
        },
        {
            "issue_type": "account_management",
            "definition": "Complaints about account status changes, freezes, access restrictions, or service/record handling.",
            "cues": ["frozen", "locked", "access", "account closed", "unable to access", "restriction"],
        },
        {
            "issue_type": "fraud_or_scam",
            "definition": "Complaints alleging fraud, scam activity, or unauthorized transactions triggering holds/blocks.",
            "cues": ["fraud", "scam", "unauthorized", "imposter", "transaction alert", "hold", "security"],
        },
        {
            "issue_type": "communication_tactics",
            "definition": "Complaints about unfair or inappropriate communications, calls, or notice delivery.",
            "cues": ["harass", "threaten", "calls", "texts", "no notice", "communication", "contact"],
        },
        {
            "issue_type": "incorrect_information",
            "definition": "Complaints about inaccurate data, record errors, or missing/incorrect disclosures.",
            "cues": ["incorrect", "wrong", "inaccurate", "reporting", "disclosure", "mistake"],
        },
        {
            "issue_type": "loan_modification",
            "definition": "Complaints related to loan modification decisions, repayment plan changes, or restructuring outcomes.",
            "cues": ["modify", "modification", "repayment plan", "restructure", "denied", "trial period"],
        },
        {
            "issue_type": "disclosure_transparency",
            "definition": "Complaints about disclosures, notices, or transparency failures.",
            "cues": ["disclosure", "notice", "terms", "explained", "transparent", "statement"],
        },
        {
            "issue_type": "closing_or_cancelling",
            "definition": "Complaints involving account closure/cancellation, cancellation handling, or termination processes.",
            "cues": ["cancel", "cancellation", "closed", "closure", "termination"],
        },
        {
            "issue_type": "communication_tactics",
            "definition": "Complaints about unfair or inappropriate communications, calls, or notice delivery.",
            "cues": ["harass", "threaten", "calls", "texts", "no notice", "communication", "contact"],
        },
        {
            "issue_type": "other",
            "definition": "Complaints that do not map cleanly to other issue types.",
            "cues": ["other", "unknown", "miscellaneous"],
        },
    ],
}


SEVERITY_RUBRIC = [
    {
        "level": "low",
        "description": "Informational errors or minor inconveniences with limited financial or access impact.",
        "cues": ["minor", "small", "informational", "typo"],
        "escalation": False,
    },
    {
        "level": "medium",
        "description": "Billing/payment disputes or moderate harm requiring timely resolution.",
        "cues": ["duplicate", "refund", "declined", "misapplied", "fee", "processing"],
        "escalation": False,
    },
    {
        "level": "high",
        "description": "Significant consumer impact, regulatory exposure, or repeated failures by the institution.",
        "cues": ["regulatory", "violation", "significant", "repeated", "multiple attempts", "large loss"],
        "escalation": True,
    },
    {
        "level": "critical",
        "description": "Severe harm: access to funds blocked, imminent litigation signals, fraud holds, or systemic issues.",
        "cues": ["frozen", "wage", "paycheck", "unauthorized", "fraud", "lawsuit", "imminent"],
        "escalation": True,
    },
]


POLICY_SNIPPETS = [
    {
        "policy_id": "disclosures_and_notice",
        "description": "Ensure customers receive clear notices and disclosures for account changes, holds, and disputes.",
        "cues": ["notice", "disclosure", "terms", "explained"],
    },
    {
        "policy_id": "error_resolution",
        "description": "Follow documented error resolution steps; confirm investigations, document outcomes, and correct records when needed.",
        "cues": ["investigation", "error", "correct", "records", "dispute"],
    },
    {
        "policy_id": "access_restoration",
        "description": "When funds access is restricted, prioritize restoration timelines and provide justification if access cannot be immediately restored.",
        "cues": ["access", "restored", "released", "funds", "blocked", "hold", "frozen"],
    },
    {
        "policy_id": "collections_and_communications",
        "description": "Ensure compliant communications and appropriate handling for debt collection scenarios.",
        "cues": ["collector", "calls", "communication", "harass"],
    },
]


ROUTING_MATRIX = {
    # Core ownership mapping.
    # This is the "company ownership graph" simplified into rules.
    "team_by_product_category": {
        "credit_card": "credit_card_operations_team",
        "checking_savings": "fraud_and_access_ops_team",
        "debt_collection": "debt_collection_team",
        "mortgage": "mortgage_servicing_team",
        "credit_reporting": "credit_reporting_team",
        "student_loan": "student_loan_servicing_team",
        "vehicle_loan": "auto_loan_team",
        "payday_loan": "consumer_lending_team",
        "money_transfer": "payments_team",
        "prepaid_card": "payments_team",
        "other": "general_complaints_team",
    },
    "executive_team": "executive_complaints_team",
    "management_escalation_team": "management_escalation_team",
}


ROOT_CAUSE_CONTROLS = [
    {
        "root_cause_category": "fraud_false_positive_hold",
        "description": "The system restricts access due to fraud rules, but the hold is not released after validation.",
        "cues": ["frozen", "hold", "fraud", "unauthorized", "paycheck", "access blocked"],
        "controls_to_check": ["fraud_model_decision_trace", "manual review queue", "release SLA"],
    },
    {
        "root_cause_category": "misapplied_payment_or_processing_bug",
        "description": "Payment processing fails to apply credits, or settlement mapping is incorrect.",
        "cues": ["misapplied", "declined", "returned", "payment not applied", "processing"],
        "controls_to_check": ["payment posting logs", "settlement mapping", "reversal workflow"],
    },
    {
        "root_cause_category": "billing_dispute_handling_gap",
        "description": "Duplicate charges or fee disputes are not investigated or corrected in the resolution workflow.",
        "cues": ["charged twice", "duplicate", "fee", "refund", "billing dispute"],
        "controls_to_check": ["chargeback/reversal logic", "fee reconciliation", "investigation SOP adherence"],
    },
    {
        "root_cause_category": "disclosure_notice_adequacy",
        "description": "Notices/disclosures for account changes are missing, unclear, or not delivered as required.",
        "cues": ["notice", "disclosure", "terms", "not provided", "unclear"],
        "controls_to_check": ["template versioning", "delivery channel logs", "customer communications review"],
    },
]


class MockCompanyPack:
    company_id: str = MOCK_COMPANY_ID
    operational_taxonomy: dict = OPERATIONAL_TAXONOMY
    severity_rubric: list = SEVERITY_RUBRIC
    policy_snippets: list = POLICY_SNIPPETS
    routing_matrix: dict = ROUTING_MATRIX
    root_cause_controls: list = ROOT_CAUSE_CONTROLS

