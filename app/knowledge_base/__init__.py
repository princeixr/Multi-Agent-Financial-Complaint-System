"""Knowledge-base foundation for regulatory and precedent graph work."""

from .bootstrap import build_phase1_seed_obligations, build_phase2_seed_failure_modes
from .graph import build_bootstrap_knowledge_graph
from .models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode
from .schemas import (
    CanonicalObligation,
    ComplaintPrecedentRecord,
    EffectivePeriod,
    FailureModeMapping,
    NormalizedDocument,
    NormalizedSection,
    SourceCitation,
)

__all__ = [
    "CanonicalObligation",
    "ComplaintPrecedentRecord",
    "EffectivePeriod",
    "FailureModeMapping",
    "KnowledgeEdge",
    "KnowledgeGraph",
    "KnowledgeNode",
    "NormalizedDocument",
    "NormalizedSection",
    "SourceCitation",
    "build_bootstrap_knowledge_graph",
    "build_phase1_seed_obligations",
    "build_phase2_seed_failure_modes",
]
