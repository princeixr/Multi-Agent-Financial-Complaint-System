from __future__ import annotations

import json
from pathlib import Path

from app.knowledge_base.bootstrap import (
    build_phase1_seed_obligations,
    build_phase2_seed_failure_modes,
)
from app.knowledge_base.graph import build_bootstrap_knowledge_graph
from app.knowledge_base.models import KnowledgeGraph


EXPORT_DIR = Path("knowledge_base/exports")


def _sanitize_mermaid(text: str) -> str:
    return (
        text.replace('"', "'")
        .replace("(", "[")
        .replace(")", "]")
        .replace("/", " / ")
        .replace("&", " and ")
        .replace(":", " -")
    )


def graph_to_mermaid(graph: KnowledgeGraph) -> str:
    lines = [
        "flowchart TD",
        "    classDef layer fill:#DCEBFF,stroke:#4C78A8,color:#102A43",
        "    classDef source_group fill:#E8F5E9,stroke:#2E7D32,color:#1B4332",
        "    classDef source_family fill:#F1F8E9,stroke:#689F38,color:#2F3E1F",
        "    classDef store fill:#FFF3E0,stroke:#EF6C00,color:#663C00",
        "    classDef entity_type fill:#F3E5F5,stroke:#8E24AA,color:#4A148C",
        "    classDef relationship_type fill:#FCE4EC,stroke:#D81B60,color:#880E4F",
        "    classDef phase fill:#E0F7FA,stroke:#00838F,color:#004D40",
    ]

    for node in graph.nodes:
        lines.append(f'    {node.id}["{_sanitize_mermaid(node.label)}"]')
        lines.append(f"    class {node.id} {node.node_type}")

    for edge in graph.edges:
        relation = _sanitize_mermaid(edge.relation)
        lines.append(f"    {edge.source} -->|{relation}| {edge.target}")

    return "\n".join(lines) + "\n"


def graph_to_markdown(graph: KnowledgeGraph) -> str:
    summary = graph.summary()
    lines = [
        "# Bootstrap Knowledge Graph",
        "",
        "This artifact is generated from the source inventory and layer design defined in `architecture.md`.",
        "",
        "## Summary",
        "",
        f"- Graph name: `{summary['name']}`",
        f"- Nodes: `{summary['node_count']}`",
        f"- Edges: `{summary['edge_count']}`",
        f"- Node types: `{summary['node_types']}`",
        "",
        "## Mermaid View",
        "",
        "```mermaid",
        graph_to_mermaid(graph).rstrip(),
        "```",
        "",
        "## Source Families",
        "",
    ]

    source_nodes = [node for node in graph.nodes if node.node_type == "source_family"]
    for node in sorted(source_nodes, key=lambda item: item.label):
        tier = node.metadata.get("tier", "?")
        outputs = ", ".join(node.metadata.get("outputs", []))
        lines.extend(
            [
                f"### {node.label}",
                "",
                f"- Tier: `{tier}`",
                f"- Authority: `{node.metadata.get('authority_type', '')}`",
                f"- Document types: `{', '.join(node.metadata.get('document_types', []))}`",
                f"- Outputs: `{outputs}`",
            ]
        )
        urls = node.metadata.get("urls", [])
        if urls:
            lines.append("- URLs:")
            for url in urls:
                lines.append(f"  - {url}")
        lines.append("")

    return "\n".join(lines)


def export_bootstrap_graph(export_dir: Path = EXPORT_DIR) -> dict[str, str]:
    graph = build_bootstrap_knowledge_graph()
    obligations = build_phase1_seed_obligations()
    failure_modes = build_phase2_seed_failure_modes()
    export_dir.mkdir(parents=True, exist_ok=True)

    json_path = export_dir / "bootstrap_knowledge_graph.json"
    mermaid_path = export_dir / "bootstrap_knowledge_graph.mmd"
    markdown_path = export_dir / "bootstrap_knowledge_graph.md"
    obligations_path = export_dir / "phase1_seed_obligations.json"
    failure_modes_path = export_dir / "phase2_seed_failure_modes.json"

    json_path.write_text(json.dumps(graph.model_dump(), indent=2), encoding="utf-8")
    mermaid_path.write_text(graph_to_mermaid(graph), encoding="utf-8")
    markdown_path.write_text(graph_to_markdown(graph), encoding="utf-8")
    obligations_path.write_text(
        json.dumps([item.model_dump() for item in obligations], indent=2),
        encoding="utf-8",
    )
    failure_modes_path.write_text(
        json.dumps([item.model_dump() for item in failure_modes], indent=2),
        encoding="utf-8",
    )

    return {
        "json": str(json_path),
        "mermaid": str(mermaid_path),
        "markdown": str(markdown_path),
        "phase1_obligations": str(obligations_path),
        "phase2_failure_modes": str(failure_modes_path),
    }


if __name__ == "__main__":
    paths = export_bootstrap_graph()
    for label, path in paths.items():
        print(f"{label}: {path}")
