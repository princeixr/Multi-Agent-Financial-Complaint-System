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
_ASSIGNEE_ID = os.getenv(
    "JIRA_ASSIGNEE_ID", "712020:ef925fc6-9afb-45bf-87d3-e42290a0fca5"
)

# Map internal risk_level strings → Jira priority names
_RISK_TO_PRIORITY: dict[str, str] = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "minimal": "Low",
}

# Map internal routing team names → Atlassian Team UUIDs (customfield_10001)
# Add more entries here as new Jira teams are created.
_TEAM_ID_MAP: dict[str, str] = {
    # Credit Card team — https://home.atlassian.com/.../team/fbca6800-f186-4e94-b412-aa92d881e15e
    "credit_card_team": "fbca6800-f186-4e94-b412-aa92d881e15e",
    "credit_card_operations_team": "fbca6800-f186-4e94-b412-aa92d881e15e",
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

    fields: dict[str, Any] = {
        "project": {"key": _PROJECT_KEY},
        "summary": summary,
        "description": description,
        "issuetype": {"name": "Task"},
        "assignee": {"id": _ASSIGNEE_ID},
        "priority": {"name": priority_name},
        "labels": labels,
    }

    if atlassian_team_id:
        # customfield_10001 is the Atlassian Team field in this Jira project
        fields["customfield_10001"] = atlassian_team_id
        logger.info("Assigning ticket to Atlassian team %s", atlassian_team_id)

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
