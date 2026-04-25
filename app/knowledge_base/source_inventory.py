from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceFamily:
    id: str
    label: str
    source_group: str
    tier: int
    authority_type: str
    document_types: tuple[str, ...]
    supports_layers: tuple[str, ...]
    outputs: tuple[str, ...]
    urls: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class SourceGroup:
    id: str
    label: str
    notes: str = ""
    families: tuple[SourceFamily, ...] = field(default_factory=tuple)


SOURCE_GROUPS: tuple[SourceGroup, ...] = (
    SourceGroup(
        id="cfpb_complaints",
        label="CFPB complaints and taxonomy",
        notes="Observational complaint history and taxonomy semantics.",
        families=(
            SourceFamily(
                id="cfpb_consumer_complaint_database",
                label="CFPB Consumer Complaint Database",
                source_group="cfpb_complaints",
                tier=3,
                authority_type="official observational source",
                document_types=("csv", "json", "api export"),
                supports_layers=("complaint_precedent_graph", "lightrag_evidence_layer"),
                outputs=(
                    "complaint records",
                    "response patterns",
                    "timeliness signals",
                    "narrative clusters",
                ),
                urls=("https://www.consumerfinance.gov/data-research/consumer-complaints/",),
            ),
            SourceFamily(
                id="cfpb_complaint_field_definitions",
                label="CFPB complaint field definitions and release notes",
                source_group="cfpb_complaints",
                tier=1,
                authority_type="official metadata source",
                document_types=("html", "documentation"),
                supports_layers=("complaint_precedent_graph",),
                outputs=("field semantics", "taxonomy version lineage", "trust hierarchy hints"),
                urls=(
                    "https://www.consumerfinance.gov/complaint/data-use/",
                    "https://cfpb.github.io/api/ccdb/fields.html",
                    "https://cfpb.github.io/api/ccdb/release-notes.html",
                ),
            ),
            SourceFamily(
                id="cfpb_complaint_product_coverage",
                label="CFPB complaint product coverage",
                source_group="cfpb_complaints",
                tier=2,
                authority_type="official scope reference",
                document_types=("html",),
                supports_layers=("canonical_regulatory_graph", "complaint_precedent_graph"),
                outputs=("public complaint product universe",),
                urls=("https://www.consumerfinance.gov/complaint/",),
            ),
        ),
    ),
    SourceGroup(
        id="cfpb_regulations",
        label="CFPB regulations and interpretations",
        notes="Primary bureau regulations, commentary, and model forms.",
        families=(
            SourceFamily(
                id="cfpb_regulations_portal",
                label="CFPB regulations portal and CFR pages",
                source_group="cfpb_regulations",
                tier=1,
                authority_type="primary regulatory source",
                document_types=("html", "regulatory text", "interpretation pages"),
                supports_layers=("canonical_regulatory_graph", "lightrag_evidence_layer"),
                outputs=(
                    "regulations",
                    "regulation parts",
                    "sections",
                    "official interpretations",
                    "model forms",
                ),
                urls=(
                    "https://www.consumerfinance.gov/rules-policy/regulations/",
                    "https://www.consumerfinance.gov/rules-policy/final-rules/code-federal-regulations/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1005/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1026/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1022/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1006/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1024/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1002/",
                    "https://www.consumerfinance.gov/rules-policy/regulations/1030/",
                ),
            ),
        ),
    ),
    SourceGroup(
        id="federal_regulatory_feeds",
        label="GovInfo and Federal Register",
        notes="Structured machine-readable regulation snapshots and amendment lineage.",
        families=(
            SourceFamily(
                id="govinfo_cfr_bulk_xml",
                label="GovInfo CFR bulk XML and API",
                source_group="federal_regulatory_feeds",
                tier=1,
                authority_type="primary structured source",
                document_types=("xml", "metadata api"),
                supports_layers=("canonical_regulatory_graph", "lightrag_evidence_layer"),
                outputs=(
                    "canonical section identity",
                    "structured CFR snapshots",
                    "source metadata",
                ),
                urls=(
                    "https://www.govinfo.gov/app/collection/cfr/",
                    "https://www.govinfo.gov/bulkdata/",
                    "https://www.govinfo.gov/developers",
                    "https://www.govinfo.gov/help/cfr",
                ),
            ),
            SourceFamily(
                id="federal_register_updates",
                label="Federal Register rule tracking",
                source_group="federal_regulatory_feeds",
                tier=1,
                authority_type="primary amendment source",
                document_types=("api", "xml", "rule notices"),
                supports_layers=("canonical_regulatory_graph", "lightrag_evidence_layer"),
                outputs=("effective-date updates", "amendment lineage", "freshness monitoring"),
                urls=(
                    "https://www.federalregister.gov/developers/documentation/api/v1",
                    "https://www.federalregister.gov/reader-aids/developer-resources",
                    "https://www.govinfo.gov/help/fr",
                ),
            ),
        ),
    ),
    SourceGroup(
        id="supervision_and_exams",
        label="Supervisory and examination guidance",
        notes="Control expectations, consumer harm framing, and examination logic.",
        families=(
            SourceFamily(
                id="cfpb_supervision_manual",
                label="CFPB Supervision and Examination Manual",
                source_group="supervision_and_exams",
                tier=2,
                authority_type="official supervisory guidance",
                document_types=("pdf", "html"),
                supports_layers=("supervisory_control_graph", "lightrag_evidence_layer"),
                outputs=("exam logic", "risk themes", "consumer harm framing"),
                urls=(
                    "https://www.consumerfinance.gov/compliance/supervision-examinations/",
                    "https://files.consumerfinance.gov/f/documents/cfpb_supervision-and-examination-manual.pdf",
                ),
            ),
            SourceFamily(
                id="cfpb_cmr_exam_procedures",
                label="CFPB Compliance Management Review Examination Procedures",
                source_group="supervision_and_exams",
                tier=2,
                authority_type="official supervisory procedures",
                document_types=("html",),
                supports_layers=("supervisory_control_graph", "lightrag_evidence_layer"),
                outputs=("control expectations", "CMS evaluation logic", "service-provider oversight themes"),
                urls=("https://www.consumerfinance.gov/compliance/supervision-examinations/compliance-management-review-examination-procedures/",),
            ),
            SourceFamily(
                id="occ_comptrollers_handbook",
                label="OCC Comptroller's Handbook",
                source_group="supervision_and_exams",
                tier=2,
                authority_type="official supervisory guidance",
                document_types=("html", "pdf"),
                supports_layers=("supervisory_control_graph", "lightrag_evidence_layer"),
                outputs=("consumer compliance risk framing", "CMS guidance", "UDAAP examination framing"),
                urls=(
                    "https://www.occ.treas.gov/publications-and-resources/publications/comptrollers-handbook/index-comptrollers-handbook.html",
                    "https://www.occ.treas.gov/publications-and-resources/publications/comptrollers-handbook/files/compliance-mgmt-systems/index-compliance-management-systems.html",
                    "https://www.occ.treas.gov/publications-and-resources/publications/comptrollers-handbook/files/unfair-deceptive-act/index-udaap.html",
                ),
            ),
            SourceFamily(
                id="fdic_compliance_manual",
                label="FDIC Consumer Compliance Examination Manual",
                source_group="supervision_and_exams",
                tier=2,
                authority_type="official supervisory guidance",
                document_types=("html",),
                supports_layers=("supervisory_control_graph", "lightrag_evidence_layer"),
                outputs=("CMS expectations", "consumer harm evaluation", "supervisory structure"),
                urls=(
                    "https://www.fdic.gov/consumer-compliance-examination-manual",
                    "https://www.fdic.gov/consumer-compliance-examination-manual/table-contents",
                ),
            ),
            SourceFamily(
                id="ffiec_bsa_aml_manual",
                label="FFIEC BSA/AML Manual and procedures",
                source_group="supervision_and_exams",
                tier=2,
                authority_type="official supervisory guidance",
                document_types=("html",),
                supports_layers=("supervisory_control_graph", "lightrag_evidence_layer"),
                outputs=("AML risk frameworks", "CIP/KYC procedures", "monitoring expectations"),
                urls=(
                    "https://bsaaml.ffiec.gov/manual",
                    "https://bsaaml.ffiec.gov/examprocedures",
                    "https://www.ffiec.gov/",
                ),
            ),
            SourceFamily(
                id="fincen_guidance",
                label="FinCEN guidance",
                source_group="supervision_and_exams",
                tier=2,
                authority_type="official interpretive guidance",
                document_types=("html", "advisories"),
                supports_layers=("supervisory_control_graph", "lightrag_evidence_layer"),
                outputs=("BSA/AML clarifications", "industry-specific risk guidance"),
                urls=("https://www.fincen.gov/resources/statutes-regulations/guidance",),
            ),
        ),
    ),
    SourceGroup(
        id="agreements_and_disclosures",
        label="Product agreements and disclosures",
        notes="Issuer and product terms that drive complaint expectations and clause-level evidence.",
        families=(
            SourceFamily(
                id="cfpb_credit_card_agreements",
                label="CFPB credit card agreement database",
                source_group="agreements_and_disclosures",
                tier=2,
                authority_type="official agreement source",
                document_types=("pdf", "html", "downloadable agreements"),
                supports_layers=("lightrag_evidence_layer", "canonical_regulatory_graph"),
                outputs=("fees", "disclosures", "product terms", "issuer-specific clauses"),
                urls=(
                    "https://www.consumerfinance.gov/credit-cards/agreements/",
                    "https://www.consumerfinance.gov/credit-cards/agreements/archive/",
                    "https://www.consumerfinance.gov/data-research/credit-card-data/",
                ),
            ),
            SourceFamily(
                id="cfpb_prepaid_agreements",
                label="CFPB prepaid account agreements",
                source_group="agreements_and_disclosures",
                tier=2,
                authority_type="official agreement source",
                document_types=("pdf", "html", "downloadable agreements"),
                supports_layers=("lightrag_evidence_layer", "canonical_regulatory_graph"),
                outputs=("fee terms", "dispute terms", "product comparison context"),
                urls=(
                    "https://www.consumerfinance.gov/data-research/prepaid-accounts/",
                    "https://www.consumerfinance.gov/data-research/prepaid-accounts/download-agreements/",
                ),
            ),
        ),
    ),
    SourceGroup(
        id="internal_sources",
        label="Internal institutional sources",
        notes="Company-owned policy, routing, and operational control context with restricted access.",
        families=(
            SourceFamily(
                id="internal_policy_and_operations",
                label="Internal policy, SOP, routing, and operational artifacts",
                source_group="internal_sources",
                tier=4,
                authority_type="institution-specific source",
                document_types=("pdf", "docx", "spreadsheet", "wiki", "ticket exports"),
                supports_layers=(
                    "supervisory_control_graph",
                    "lightrag_evidence_layer",
                ),
                outputs=(
                    "routing logic",
                    "escalation thresholds",
                    "refund authority matrix",
                    "playbooks",
                    "product catalog mappings",
                ),
                notes="Must remain access-controlled and separated from public-source retrieval.",
            ),
        ),
    ),
)


LAYER_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "id": "canonical_regulatory_graph",
        "label": "Canonical Regulatory Graph",
        "description": "Curated truth for products, regulations, sections, obligations, deadlines, and evidence requirements.",
    },
    {
        "id": "supervisory_control_graph",
        "label": "Supervisory / Control Graph",
        "description": "Operational and supervisory mapping for controls, failure modes, risk indicators, and remediation.",
    },
    {
        "id": "complaint_precedent_graph",
        "label": "Complaint Precedent Graph",
        "description": "Observational layer over complaint history, response patterns, narrative clusters, and trend signals.",
    },
    {
        "id": "lightrag_evidence_layer",
        "label": "LightRAG Evidence Layer",
        "description": "Text-rich retrieval layer for manuals, interpretations, agreements, narratives, and policies.",
    },
)


STORE_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "id": "raw_object_store",
        "label": "Raw Object Store",
        "description": "Immutable raw files with acquisition lineage and checksums.",
    },
    {
        "id": "normalized_document_store",
        "label": "Normalized Document Store",
        "description": "Normalized docs, sections, chunks, and metadata for downstream extraction and retrieval.",
    },
    {
        "id": "canonical_graph_store",
        "label": "Canonical Graph Store",
        "description": "Deterministic graph backing products, regulations, obligations, controls, and mappings.",
    },
    {
        "id": "analytical_store",
        "label": "Analytical Store",
        "description": "Trend tables, clusters, monitoring signals, and feature computation.",
    },
    {
        "id": "vector_retrieval_store",
        "label": "Vector / Retrieval Store",
        "description": "Semantic retrieval index for narratives, chunks, and evidence recall.",
    },
)


ENTITY_TYPE_DEFINITIONS: tuple[dict[str, object], ...] = (
    {"id": "entity_product", "label": "Product", "layer": "canonical_regulatory_graph"},
    {"id": "entity_regulation", "label": "Regulation", "layer": "canonical_regulatory_graph"},
    {"id": "entity_reg_section", "label": "RegSection", "layer": "canonical_regulatory_graph"},
    {"id": "entity_obligation", "label": "Obligation", "layer": "canonical_regulatory_graph"},
    {"id": "entity_deadline", "label": "Deadline", "layer": "canonical_regulatory_graph"},
    {"id": "entity_evidence_requirement", "label": "EvidenceRequirement", "layer": "canonical_regulatory_graph"},
    {"id": "entity_control", "label": "Control", "layer": "supervisory_control_graph"},
    {"id": "entity_failure_mode", "label": "FailureMode", "layer": "supervisory_control_graph"},
    {"id": "entity_risk_indicator", "label": "RiskIndicator", "layer": "supervisory_control_graph"},
    {"id": "entity_remediation_action", "label": "RemediationAction", "layer": "supervisory_control_graph"},
    {"id": "entity_complaint", "label": "Complaint", "layer": "complaint_precedent_graph"},
    {"id": "entity_narrative_cluster", "label": "NarrativeCluster", "layer": "complaint_precedent_graph"},
    {"id": "entity_response_type", "label": "ResponseType", "layer": "complaint_precedent_graph"},
    {"id": "entity_internal_policy", "label": "InternalPolicy", "layer": "supervisory_control_graph"},
)


RELATIONSHIP_TYPE_DEFINITIONS: tuple[dict[str, object], ...] = (
    {"id": "rel_governed_by", "label": "GOVERNED_BY", "domain": "product-regulation"},
    {"id": "rel_contains", "label": "CONTAINS", "domain": "regulation-section"},
    {"id": "rel_imposes", "label": "IMPOSES", "domain": "section-obligation"},
    {"id": "rel_requires_evidence", "label": "REQUIRES_EVIDENCE", "domain": "obligation-evidence"},
    {"id": "rel_has_deadline", "label": "HAS_DEADLINE", "domain": "obligation-deadline"},
    {"id": "rel_evaluates", "label": "EVALUATES", "domain": "exam-control"},
    {"id": "rel_mitigates", "label": "MITIGATES", "domain": "control-failure"},
    {"id": "rel_raises", "label": "RAISES", "domain": "failure-risk"},
    {"id": "rel_belongs_to", "label": "BELONGS_TO", "domain": "complaint-cluster"},
    {"id": "rel_suggests", "label": "SUGGESTS", "domain": "cluster-failure"},
)


PHASE_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "id": "phase_1",
        "label": "Phase 1: Canonical complaint-risk spine",
        "description": "CFPB complaints, priority regulations, CFR ingestion, complaint precedent graph, read-only graph queries for Risk and Root-Cause agents.",
    },
    {
        "id": "phase_2",
        "label": "Phase 2: Supervisory and control intelligence",
        "description": "Supervision manuals, CMS procedures, OCC/FDIC/FFIEC guidance, failure modes, controls, and risk indicators.",
    },
    {
        "id": "phase_3",
        "label": "Phase 3: Agreement and product-document intelligence",
        "description": "Agreement clauses, fees, disclosures, dispute terms, and product-document mappings.",
    },
    {
        "id": "phase_4",
        "label": "Phase 4: Internal policy and operations intelligence",
        "description": "SOPs, routing rules, SLAs, escalation policies, and team/playbook mappings.",
    },
)
