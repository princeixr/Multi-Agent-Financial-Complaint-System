from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field


NodeType = Literal[
    "layer",
    "store",
    "source_group",
    "source_family",
    "document_type",
    "entity_type",
    "relationship_type",
    "phase",
]


class KnowledgeNode(BaseModel):
    id: str
    label: str
    node_type: NodeType
    description: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class KnowledgeEdge(BaseModel):
    source: str
    target: str
    relation: str
    description: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class KnowledgeGraph(BaseModel):
    name: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)

    def node(self, node_id: str) -> KnowledgeNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"Unknown node id: {node_id}")

    def summary(self) -> dict[str, object]:
        node_counts = Counter(node.node_type for node in self.nodes)
        return {
            "name": self.name,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "node_types": dict(sorted(node_counts.items())),
        }
