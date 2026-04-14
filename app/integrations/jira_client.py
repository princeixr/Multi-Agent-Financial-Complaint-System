"""Jira REST API client for the TriageAI complaint pipeline.

Creates a Jira Task in the configured project whenever the routing agent
assigns a complaint to a team.  Authentication uses HTTP Basic Auth with an
Atlassian API token (email + token).

Required environment variables
--------------------------------
JIRA_BASE_URL        https://triageai.atlassian.net
JIRA_USER_EMAIL      sairahul2721@gmail.com
JIRA_API_TOKEN       <generated from id.atlassian.com>
JIRA_PROJECT_KEY     KAN                          (default: KAN)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_BASE_URL = os.getenv("JIRA_BASE_URL", "https://triageai.atlassian.net")
_USER_EMAIL = os.getenv("JIRA_USER_EMAIL", "sairahul2721@gmail.com")
_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "KAN")


# Map internal risk_level strings → Jira priority names
_RISK_TO_PRIORITY: dict[str, str] = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "minimal": "Low",
}

# Map internal routing team names → Atlassian Team UUIDs (customfield_10001)
#
# HOW TO ADD A NEW TEAM:
# 1. Create a team in Atlassian at https://home.atlassian.com/YOUR_ORG/teams
# 2. Copy the team UUID from the URL (the last path segment)
# 3. Add a mapping below: "routing_team_name": "atlassian-team-uuid"

_TEAM_ID_MAP: dict[str, str] = {
    # ── Product-based teams (from ROUTING_MATRIX.team_by_product_category) ──
    "credit_card_team": "fbca6800-f186-4e94-b412-aa92d881e15e",
    "credit_card_operations_team": "fbca6800-f186-4e94-b412-aa92d881e15e",
    "fraud_and_access_ops_team": "76558461-8a3e-4c8f-af73-4b3a83f5659e",
    "debt_collection_team": "220c7d09-1595-442d-92c3-79cb74af2af3",
    "mortgage_servicing_team": "f79caa32-cf53-4299-80c5-799b3e0c7bad",
    "credit_reporting_team": "eba1f6e3-374f-42c7-9833-47b7c3adb428",
    "student_loan_servicing_team": "3b322054-5dea-4d61-8cdb-86db328de7fd",
    "auto_loan_team": "8fcc518b-015f-4344-8c78-70da2668a59b",
    "consumer_lending_team": "84682530-52f5-413c-997a-3fcc0ff9fb0e",
    "payments_team": "164363c2-4b7e-44e3-b7c4-829a20d7cd22",
    "general_complaints_team": "2c759485-7ae6-470e-a42c-2dcb5d33b41c",
    # ── Fallback teams from routing.py _PRODUCT_TO_TEAM defaults ──
    "banking_team": "76558461-8a3e-4c8f-af73-4b3a83f5659e",
    "mortgage_team": "f79caa32-cf53-4299-80c5-799b3e0c7bad",
    "student_loan_team": "3b322054-5dea-4d61-8cdb-86db328de7fd",
    # ── Escalation teams ──
    "executive_complaints_team": "0b9ef1e3-ff45-4ab5-affc-73d811667f9b",
    "management_escalation_team": "227158cb-99a5-4e52-bdda-329baea20900",
}

_JIRA_REST = f"{_BASE_URL}/rest/api/3"


# ── ADF (Atlassian Document Format) helpers ──────────────────────────────────


def _adf_text(text: str) -> dict:
    return {"type": "text", "text": text}


def _adf_bold(text: str) -> dict:
    return {"type": "text", "text": text, "marks": [{"type": "strong"}]}


def _adf_para(*nodes: dict) -> dict:
    return {"type": "paragraph", "content": list(nodes)}


def _adf_heading(text: str, level: int = 3) -> dict:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [_adf_text(text)],
    }


def _adf_rule() -> dict:
    return {"type": "rule"}


def _adf_bullet_list(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [_adf_para(_adf_text(item))],
            }
            for item in items
            if item
        ],
    }


def _adf_doc(*blocks: dict | None) -> dict[str, Any]:
    """Build an ADF document from block-level nodes (paragraphs, headings, etc.)."""
    return {
        "version": 1,
        "type": "doc",
        "content": [b for b in blocks if b is not None],
    }


def _truncate(text: str, max_len: int = 800) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(username=_USER_EMAIL, password=_API_TOKEN)


# ── Public API ────────────────────────────────────────────────────────────────


def create_complaint_ticket(
    *,
    case_id: str,
    team: str,
    product_category: str | None,
    issue_type: str | None = None,
    risk_level: str | None,
    risk_score: float | None = None,
    risk_reasoning: str | None = None,
    regulatory_risk: bool = False,
    financial_impact: float | None = None,
    channel: str | None,
    consumer_narrative: str | None,
    resolution_action: str | None = None,
    resolution_description: str | None = None,
    resolution_reasoning: str | None = None,
    estimated_resolution_days: int | None = None,
    monetary_amount: float | None = None,
    root_cause_category: str | None = None,
    root_cause_reasoning: str | None = None,
    controls_to_check: list[str] | None = None,
    compliance_flags: list[str] | None = None,
    classification_reasoning: str | None = None,
    company: str | None = None,
    state: str | None = None,
) -> dict[str, str]:
    """Create a Jira Task for a routed complaint and return ``{key, url}``.

    Raises
    ------
    RuntimeError
        If ``JIRA_API_TOKEN`` is not set or the API call fails.
    """
    if not _API_TOKEN:
        raise RuntimeError(
            "JIRA_API_TOKEN is not set. "
            "Generate one at https://id.atlassian.com/manage-profile/security/api-tokens "
            "and add it to your .env file."
        )

    short_id = case_id[:8].upper()
    product_label = (product_category or "unknown").replace("_", " ").title()
    issue_label = (issue_type or "unknown").replace("_", " ").title()
    risk_label = risk_level or "unknown"
    priority_name = _RISK_TO_PRIORITY.get(risk_label.lower(), "Medium")
    team_label = team.replace("_", " ").title()

    summary = f"[{team_label}] {product_label} – {issue_label} (#{short_id})"

    # ── Build structured ADF description ─────────────────────────────────
    blocks: list[dict | None] = []

    # Header
    blocks.append(_adf_para(
        _adf_text("🔔 Automated ticket created by the "),
        _adf_bold("TriageAI complaint pipeline"),
        _adf_text("."),
    ))

    # ── Case Overview ────────────────────────────────────────────────────
    blocks.append(_adf_heading("📋 Case Overview", 2))
    blocks.append(_adf_bullet_list([
        f"Case ID: {case_id}",
        f"Product: {product_label}",
        f"Issue Type: {issue_label}",
        f"Channel: {(channel or 'web').replace('_', ' ').title()}",
        f"Company: {company or 'N/A'}",
        f"State: {state or 'N/A'}",
        f"Routed To: {team_label}",
    ]))

    # ── Consumer Complaint ───────────────────────────────────────────────
    blocks.append(_adf_rule())
    blocks.append(_adf_heading("📝 Consumer Complaint", 2))
    blocks.append(_adf_para(_adf_text(
        _truncate(consumer_narrative or "No narrative provided.")
    )))

    # ── Classification ───────────────────────────────────────────────────
    if classification_reasoning:
        blocks.append(_adf_rule())
        blocks.append(_adf_heading("🏷️ Classification", 2))
        blocks.append(_adf_para(
            _adf_bold("Product: "), _adf_text(product_label),
            _adf_text("  |  "),
            _adf_bold("Issue: "), _adf_text(issue_label),
        ))
        blocks.append(_adf_para(
            _adf_bold("Reasoning: "),
            _adf_text(_truncate(classification_reasoning, 500)),
        ))

    # ── Risk Assessment ──────────────────────────────────────────────────
    blocks.append(_adf_rule())
    blocks.append(_adf_heading("⚠️ Risk Assessment", 2))

    risk_items = [f"Risk Level: {risk_label.upper()}"]
    if risk_score is not None:
        risk_items.append(f"Risk Score: {risk_score:.1f} / 100")
    if financial_impact is not None:
        risk_items.append(f"Estimated Financial Impact: ${financial_impact:,.2f}")
    if regulatory_risk:
        risk_items.append("⚖️ REGULATORY RISK: Yes — potential regulatory exposure")
    blocks.append(_adf_bullet_list(risk_items))

    if risk_reasoning:
        blocks.append(_adf_para(
            _adf_bold("Assessment: "),
            _adf_text(_truncate(risk_reasoning, 500)),
        ))

    # ── Root Cause Hypothesis ────────────────────────────────────────────
    if root_cause_category or root_cause_reasoning:
        blocks.append(_adf_rule())
        blocks.append(_adf_heading("🔍 Root Cause Hypothesis", 2))
        if root_cause_category:
            blocks.append(_adf_para(
                _adf_bold("Category: "),
                _adf_text(root_cause_category.replace("_", " ").title()),
            ))
        if root_cause_reasoning:
            blocks.append(_adf_para(
                _adf_bold("Analysis: "),
                _adf_text(_truncate(root_cause_reasoning, 500)),
            ))
        if controls_to_check:
            blocks.append(_adf_para(_adf_bold("Controls to verify:")))
            blocks.append(_adf_bullet_list(controls_to_check))

    # ── Proposed Resolution ──────────────────────────────────────────────
    blocks.append(_adf_rule())
    blocks.append(_adf_heading("✅ Proposed Resolution", 2))

    if resolution_action:
        action_label = resolution_action.replace("_", " ").title()
        blocks.append(_adf_para(
            _adf_bold("Recommended Action: "), _adf_text(action_label),
        ))
    if monetary_amount is not None:
        blocks.append(_adf_para(
            _adf_bold("Monetary Relief: "), _adf_text(f"${monetary_amount:,.2f}"),
        ))
    if estimated_resolution_days is not None:
        blocks.append(_adf_para(
            _adf_bold("Estimated Resolution: "),
            _adf_text(f"{estimated_resolution_days} business day(s)"),
        ))
    if resolution_description:
        blocks.append(_adf_para(
            _adf_bold("Description: "),
            _adf_text(_truncate(resolution_description, 600)),
        ))
    if resolution_reasoning:
        blocks.append(_adf_para(
            _adf_bold("Reasoning: "),
            _adf_text(_truncate(resolution_reasoning, 400)),
        ))

    # ── Compliance Flags ─────────────────────────────────────────────────
    if compliance_flags:
        blocks.append(_adf_rule())
        blocks.append(_adf_heading("🛡️ Compliance Flags", 2))
        blocks.append(_adf_bullet_list(compliance_flags))

    # ── Next Steps ───────────────────────────────────────────────────────
    blocks.append(_adf_rule())
    blocks.append(_adf_heading("👉 Next Steps for Team", 2))

    next_steps = [
        "Review the consumer complaint narrative above.",
        "Verify the root cause hypothesis and check listed controls.",
        "Validate or adjust the proposed resolution.",
    ]
    if regulatory_risk:
        next_steps.append("⚖️ Flag for regulatory review — this case has regulatory exposure.")
    if compliance_flags:
        next_steps.append("Address compliance flags before closing.")
    if monetary_amount is not None:
        next_steps.append(f"Process monetary relief of ${monetary_amount:,.2f} if approved.")
    next_steps.append("Update this ticket with findings and close when resolved.")
    blocks.append(_adf_bullet_list(next_steps))

    description = _adf_doc(*blocks)

    labels = [
        "complaint",
        "auto-generated",
        team.replace(" ", "-"),
        risk_label.lower(),
    ]
    if regulatory_risk:
        labels.append("regulatory-risk")

    # Resolve Atlassian Team ID for this routing destination (if mapped)
    atlassian_team_id = _TEAM_ID_MAP.get(team)
    if not atlassian_team_id:
        fallback = _TEAM_ID_MAP["general_complaints_team"]
        logger.warning(
            "No Atlassian Team UUID mapped for routing team %r; "
            "falling back to general_complaints_team. Add a mapping to _TEAM_ID_MAP.",
            team,
        )
        atlassian_team_id = fallback

    fields: dict[str, Any] = {
        "project": {"key": _PROJECT_KEY},
        "summary": summary,
        "description": description,
        "issuetype": {"name": "Task"},

        "priority": {"name": priority_name},
        "labels": labels,
    }

    # customfield_10001 is the Atlassian Team field in this Jira project
    fields["customfield_10001"] = atlassian_team_id
    logger.info("Assigning ticket to Atlassian team %s (routing team: %s)", atlassian_team_id, team)

    payload: dict[str, Any] = {"fields": fields}

    logger.info(
        "Creating Jira ticket in project %s for case %s (team=%s, priority=%s)",
        _PROJECT_KEY,
        case_id,
        team,
        priority_name,
    )

    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{_JIRA_REST}/issue",
            auth=_auth(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json=payload,
        )

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Jira API returned {resp.status_code}: {resp.text[:400]}"
        )

    data = resp.json()
    issue_key = data["key"]
    issue_url = f"{_BASE_URL}/browse/{issue_key}"

    logger.info("Jira ticket created: %s → %s", issue_key, issue_url)
    return {"key": issue_key, "url": issue_url}
