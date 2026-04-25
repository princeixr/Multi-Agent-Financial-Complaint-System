from __future__ import annotations

from app.knowledge_base.schemas import (
    CanonicalObligation,
    EffectivePeriod,
    FailureModeMapping,
    SourceCitation,
)


def build_phase1_seed_obligations() -> list[CanonicalObligation]:
    return [
        CanonicalObligation(
            obligation_id="reg_e_error_resolution_seed",
            label="Reg E error-resolution investigation and response",
            summary="Seed obligation for unauthorized EFT complaint handling. Final extraction must separate notice timing, investigation, provisional credit, and response duties by section.",
            regulation="Regulation E",
            regulation_section="12 CFR 1005.11",
            trigger_conditions=[
                "consumer asserts an error or unauthorized EFT",
                "notice received within applicable timing window",
            ],
            evidence_requirements=[
                "transaction history",
                "authorization evidence",
                "consumer notice date",
                "statement delivery timeline",
            ],
            deadlines=[
                "investigation timing must be determined from validated regulation text",
            ],
            consumer_rights=[
                "consumer receives error-resolution process protections",
            ],
            effective_period=EffectivePeriod(valid_from="seed"),
            citations=[
                SourceCitation(
                    source_family_id="cfpb_regulations_portal",
                    source_url="https://www.consumerfinance.gov/rules-policy/regulations/1005/11/",
                    document_title="Regulation E section 1005.11",
                    citation_anchor="12 CFR 1005.11",
                    tier=1,
                ),
                SourceCitation(
                    source_family_id="govinfo_cfr_bulk_xml",
                    source_url="https://www.govinfo.gov/app/collection/cfr/",
                    document_title="GovInfo CFR bulk data",
                    citation_anchor="12 CFR 1005.11",
                    tier=1,
                ),
            ],
            validation_status="seeded",
        )
    ]


def build_phase2_seed_failure_modes() -> list[FailureModeMapping]:
    return [
        FailureModeMapping(
            failure_mode_id="unauthorized_eft_handling_breakdown_seed",
            label="Unauthorized EFT handling breakdown",
            control_domains=[
                "dispute operations",
                "fraud operations",
                "complaint handling",
            ],
            controls=[
                "error intake and triage",
                "transaction investigation workflow",
                "consumer communication controls",
            ],
            risk_indicators=[
                "repeat unauthorized transaction complaints",
                "response delay patterns",
                "missing authorization evidence",
            ],
            consumer_harm_types=[
                "fund access disruption",
                "unreimbursed loss",
                "investigation delay",
            ],
            owning_functions=[
                "disputes operations",
                "fraud operations",
            ],
            remediation_actions=[
                "review investigation SLA adherence",
                "verify provisional credit policy application",
                "inspect authorization evidence retention",
            ],
            citations=[
                SourceCitation(
                    source_family_id="cfpb_supervision_manual",
                    source_url="https://files.consumerfinance.gov/f/documents/cfpb_supervision-and-examination-manual.pdf",
                    document_title="CFPB Supervision and Examination Manual",
                    tier=2,
                ),
                SourceCitation(
                    source_family_id="cfpb_cmr_exam_procedures",
                    source_url="https://www.consumerfinance.gov/compliance/supervision-examinations/compliance-management-review-examination-procedures/",
                    document_title="CFPB Compliance Management Review Examination Procedures",
                    tier=2,
                ),
            ],
            validation_status="seeded",
        )
    ]
