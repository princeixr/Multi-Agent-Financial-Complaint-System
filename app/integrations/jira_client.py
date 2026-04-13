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
JIRA_ASSIGNEE_ID     712020:ef925fc6-...          (default: Rahul's account)
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(username=_USER_EMAIL, password=_API_TOKEN)


def _adf_doc(*paragraphs: str) -> dict[str, Any]:
    """Build a minimal Atlassian Document Format (ADF) document."""

    def _para(text: str) -> dict:
        return {
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        }

    return {
        "version": 1,
        "type": "doc",
        "content": [_para(p) for p in paragraphs if p],
    }


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


# ── Public API ────────────────────────────────────────────────────────────────


def create_complaint_ticket(
    *,
    case_id: str,
    team: str,
    product_category: str | None,
    risk_level: str | None,
    channel: str | None,
    consumer_narrative: str | None,
    resolution_summary: str | None,
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
    product_label = product_category or "Unknown Product"
    risk_label = risk_level or "unknown"
    priority_name = _RISK_TO_PRIORITY.get(risk_label.lower(), "Medium")

    summary = f"[{team}] Complaint #{short_id} – {product_label}"

    # Build ADF description paragraphs
    narrative_block = _truncate(consumer_narrative or "No narrative provided.")
    resolution_block = _truncate(resolution_summary or "No resolution proposed.")

    description = _adf_doc(
        "🔔 Automated ticket created by the TriageAI complaint pipeline.",
        "",
        f"Case ID      : {case_id}",
        f"Routed Team  : {team}",
        f"Product      : {product_label}",
        f"Risk Level   : {risk_label.title()}",
        f"Channel      : {channel or 'web'}",
        f"Company      : {company or 'N/A'}",
        f"State        : {state or 'N/A'}",
        "",
        "── Complaint Narrative ──────────────────────────────",
        narrative_block,
        "",
        "── Proposed Resolution ──────────────────────────────",
        resolution_block,
    )

    labels = ["complaint", "auto-generated", team.replace(" ", "-")]

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
