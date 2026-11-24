# Phase 07 - Memory and Knowledge

| Field | Value |
|---|---|
| Phase | 07 |
| Name | Memory & Knowledge |
| Deliverable | Versioned tenant-scoped knowledge repository, source registry, and lexical retrieval |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-07 |
| Version | 1.0 |

## Specification

Phase 07 MVP provides controlled document ingestion, immutable content
versions, deterministic chunking, and tenant-scoped lexical search. Documents
are drafts by default and must be activated before retrieval.

## Components

| Component | Implementation | Purpose |
|---|---|---|
| Repository | `KnowledgeDocument` | Tenant-owned source metadata and lifecycle |
| Version history | `KnowledgeDocumentVersion` | Immutable content revisions |
| Chunk index | `KnowledgeChunk` | Fixed-size text chunks with source offsets |
| Search | `POST /api/v1/knowledge/search` | Deterministic, case-insensitive lexical retrieval |
| Source registry | `KnowledgeSource` | Tenant-owned source metadata, credibility, license, access, and verification state |
| Access control | `nexus.knowledge.read/manage` | Tenant-scoped read and write permissions |
| Audit | `AuditEvent` | Record repository changes and search counts without content |

## Boundaries

- Document content is limited to 256 KiB; chunks are 1,200 characters with a
  200-character overlap.
- Search is lexical substring matching, not semantic/vector retrieval.
- Only active documents and their current versions are searchable.
- Source values are descriptive metadata. NEXUS does not fetch external URLs.
- Search results are not automatically inserted into AI or agent prompts.
- Content is stored as ordinary database text; deployments must protect the
  database and apply retention policies appropriate for the stored data.

## Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| MK-01 | Document records and versions are tenant-scoped | API tests |
| MK-02 | Content changes create a new immutable version | API tests |
| MK-03 | Draft/inactive content is excluded from retrieval | API tests |
| MK-04 | Search returns ranked current-version chunks only | API tests |
| MK-05 | Read/manage permissions and tenant boundaries are enforced | API tests |
| MK-06 | Audit evidence does not include document or query content | API tests |
| MK-07 | Migration applies and rolls back on supported SQLite path | Migration check |

## Out of scope

Embeddings, vector databases, semantic ranking, automatic RAG prompt
construction, external URL ingestion, document parsers, knowledge graphs, and
long-term personal memory are not included in this MVP.
