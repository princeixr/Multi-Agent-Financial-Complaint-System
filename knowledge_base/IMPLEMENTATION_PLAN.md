# Implementation Plan

The knowledge base will be built in phases so today's visible graph work becomes the base for ingestion and agent queries rather than a throwaway artifact.

## Phase 1

- Build the source inventory and graph topology from `architecture.md`
- Add normalized document and section schemas
- Implement canonical regulatory tables for:
  - source documents
  - sections
  - obligations
  - evidence requirements
  - deadlines
  - effective periods
- Keep complaint precedent retrieval in PostgreSQL + pgvector
- Expose read-only query services for Risk and Root-Cause agents

## Phase 2

- Ingest supervisory manuals and exam procedures
- Add control-domain, failure-mode, and risk-indicator structures
- Connect complaint clusters to supervisory failure modes

## Phase 3

- Ingest agreement and disclosure sources
- Extract clauses, fees, dispute terms, and issuer metadata
- Link agreement clauses to complaint themes and regulatory sections

## Phase 4

- Add internal policy and operations sources
- Map routing, SLAs, escalation rules, playbooks, and team ownership
- Extend the same backbone to Routing, Resolve, and Review agents

## Today's Deliverable

- `app/knowledge_base/` package containing graph models and source inventory
- generated graph exports under `knowledge_base/exports/`
- a concrete, inspectable knowledge graph reflecting the architecture's layers and source families
