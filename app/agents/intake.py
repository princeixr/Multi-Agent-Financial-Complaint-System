"""Intake agent – validates, normalises and enriches the raw complaint."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.schemas.case import CaseCreate, CaseRead, CaseStatus
from app.utils.pii import redact_pii

logger = logging.getLogger(__name__)


def _normalise_text(text: str) -> str:
    """Redact PII, lower-case, and collapse whitespace."""
    text = redact_pii(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def run_intake(payload: CaseCreate) -> CaseRead:
    """Execute the intake step and return an enriched case object.

    Responsibilities
    ────────────────
    • Validate required fields (Pydantic handles most of this).
    • Redact obvious PII from the narrative.
    • Normalise whitespace and casing.
    • Stamp ``submitted_at`` if missing.
    • Set status → ``intake_complete``.
    """
    logger.info("Intake agent processing new complaint")

    clean_narrative = _normalise_text(payload.consumer_narrative)

    case = CaseRead(
        consumer_narrative=clean_narrative,
        product=payload.product,
        sub_product=payload.sub_product,
        company=payload.company,
        state=payload.state,
        zip_code=payload.zip_code,
        channel=payload.channel,
        submitted_at=payload.submitted_at or datetime.utcnow(),
        status=CaseStatus.INTAKE_COMPLETE,
    )

    case.external_schema = {
        "external_product_category": payload.external_product_category,
        "external_issue_type": payload.external_issue_type,
        "requested_resolution": payload.requested_resolution,
    }

    logger.info("Intake complete – case %s", case.id)
    return case
