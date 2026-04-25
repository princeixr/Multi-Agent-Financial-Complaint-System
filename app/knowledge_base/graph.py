from __future__ import annotations

from app.knowledge_base.models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode
from app.knowledge_base.source_inventory import (
    ENTITY_TYPE_DEFINITIONS,
    LAYER_DEFINITIONS,
    PHASE_DEFINITIONS,
    RELATIONSHIP_TYPE_DEFINITIONS,
    SOURCE_GROUPS,
    STORE_DEFINITIONS,
)


def build_bootstrap_knowledge_graph() -> KnowledgeGraph:
    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []

    for layer in LAYER_DEFINITIONS:
        nodes.append(
            KnowledgeNode(
                id=str(layer["id"]),
                label=str(layer["label"]),
                node_type="layer",
                description=str(layer["description"]),
            )
        )

    for store in STORE_DEFINITIONS:
        nodes.append(
            KnowledgeNode(
                id=str(store["id"]),
                label=str(store["label"]),
                node_type="store",
                description=str(store["description"]),
            )
        )

    for group in SOURCE_GROUPS:
        nodes.append(
            KnowledgeNode(
                id=group.id,
                label=group.label,
                node_type="source_group",
                description=group.notes,
            )
        )
        edges.append(
            KnowledgeEdge(
                source=group.id,
                target="raw_object_store",
                relation="lands_in",
                description="Raw acquisitions are preserved in immutable storage.",
            )
        )
        edges.append(
            KnowledgeEdge(
                source=group.id,
                target="normalized_document_store",
                relation="normalizes_to",
                description="Raw sources are normalized into consistent documents and sections.",
            )
        )

        for family in group.families:
            nodes.append(
                KnowledgeNode(
                    id=family.id,
                    label=family.label,
                    node_type="source_family",
                    description=family.notes,
                    metadata={
                        "tier": family.tier,
                        "authority_type": family.authority_type,
                        "document_types": list(family.document_types),
                        "urls": list(family.urls),
                        "outputs": list(family.outputs),
                    },
                )
            )
            edges.append(
                KnowledgeEdge(
                    source=group.id,
                    target=family.id,
                    relation="contains",
                    description="Source group contains this source family.",
                )
            )
            edges.append(
                KnowledgeEdge(
                    source=family.id,
                    target="normalized_document_store",
                    relation="normalizes_to",
                    description="Normalized records preserve metadata, sections, and lineage.",
                )
            )
            if "complaint_precedent_graph" in family.supports_layers:
                edges.append(
                    KnowledgeEdge(
                        source=family.id,
                        target="analytical_store",
                        relation="aggregates_to",
                        description="Complaint and trend features are materialized into analytical tables.",
                    )
                )
            for layer_id in family.supports_layers:
                edges.append(
                    KnowledgeEdge(
                        source=family.id,
                        target=layer_id,
                        relation="feeds",
                        description="Source family contributes facts or retrieval evidence to this layer.",
                    )
                )

    for entity in ENTITY_TYPE_DEFINITIONS:
        nodes.append(
            KnowledgeNode(
                id=str(entity["id"]),
                label=str(entity["label"]),
                node_type="entity_type",
                description=f"Core entity type for {entity['layer']}.",
                metadata={"layer": entity["layer"]},
            )
        )
        edges.append(
            KnowledgeEdge(
                source=str(entity["layer"]),
                target=str(entity["id"]),
                relation="contains_entity",
                description="Layer contains this core entity type.",
            )
        )

    for relationship in RELATIONSHIP_TYPE_DEFINITIONS:
        nodes.append(
            KnowledgeNode(
                id=str(relationship["id"]),
                label=str(relationship["label"]),
                node_type="relationship_type",
                description=f"Representative relationship for {relationship['domain']}.",
                metadata={"domain": relationship["domain"]},
            )
        )
        edges.append(
            KnowledgeEdge(
                source="canonical_graph_store",
                target=str(relationship["id"]),
                relation="implements",
                description="Canonical graph store persists typed relationships.",
            )
        )

    store_to_layer_edges = (
        ("normalized_document_store", "canonical_regulatory_graph", "feeds"),
        ("normalized_document_store", "supervisory_control_graph", "feeds"),
        ("normalized_document_store", "complaint_precedent_graph", "feeds"),
        ("normalized_document_store", "lightrag_evidence_layer", "indexes_into"),
        ("canonical_regulatory_graph", "canonical_graph_store", "persists_in"),
        ("supervisory_control_graph", "canonical_graph_store", "persists_in"),
        ("complaint_precedent_graph", "canonical_graph_store", "persists_in"),
        ("complaint_precedent_graph", "vector_retrieval_store", "retrieves_from"),
        ("lightrag_evidence_layer", "vector_retrieval_store", "retrieves_from"),
        ("complaint_precedent_graph", "analytical_store", "measures_in"),
    )
    for source, target, relation in store_to_layer_edges:
        edges.append(
            KnowledgeEdge(
                source=source,
                target=target,
                relation=relation,
            )
        )

    for phase in PHASE_DEFINITIONS:
        nodes.append(
            KnowledgeNode(
                id=str(phase["id"]),
                label=str(phase["label"]),
                node_type="phase",
                description=str(phase["description"]),
            )
        )

    phase_links = (
        ("phase_1", "cfpb_complaints"),
        ("phase_1", "cfpb_regulations"),
        ("phase_1", "federal_regulatory_feeds"),
        ("phase_1", "canonical_regulatory_graph"),
        ("phase_1", "complaint_precedent_graph"),
        ("phase_2", "supervision_and_exams"),
        ("phase_2", "supervisory_control_graph"),
        ("phase_3", "agreements_and_disclosures"),
        ("phase_3", "lightrag_evidence_layer"),
        ("phase_4", "internal_sources"),
        ("phase_4", "supervisory_control_graph"),
    )
    for source, target in phase_links:
        edges.append(
            KnowledgeEdge(
                source=source,
                target=target,
                relation="delivers",
            )
        )

    return KnowledgeGraph(name="regulatory_complaint_knowledge_bootstrap", nodes=nodes, edges=edges)
