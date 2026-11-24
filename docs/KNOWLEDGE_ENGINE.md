# Knowledge Engine

The Knowledge Engine stores tenant-shared documents, keeps immutable content
versions, and provides deterministic lexical search. Apply schema changes with
`alembic upgrade head`.

## Permissions

| Permission | Actions |
|---|---|
| `nexus.knowledge.read` | List documents, read content/versions, search |
| `nexus.knowledge.manage` | Create, update, activate/deactivate, and delete documents |

The built-in owner/operator roles can manage knowledge; viewers can read it.
All access is tenant-scoped. Documents are shared within a tenant rather than
private to the creating user.

## Source registry

The source registry records metadata for external and internal knowledge sources
without fetching or importing their content.

```http
POST /api/v1/knowledge/sources
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "name": "OpenAlex",
  "url": "https://openalex.org",
  "source_type": "ACADEMIC_INDEX",
  "knowledge_domains": ["Computer Science", "Research"],
  "credibility": "S2",
  "status": "VERIFIED",
  "access_method": "API",
  "license": "CC0",
  "update_frequency": "DAILY",
  "security_risk": "LOW",
  "research_status": "APPROVED"
}
```

Source records support `GET /api/v1/knowledge/sources`,
`GET /api/v1/knowledge/sources/{source_id}`,
`PATCH /api/v1/knowledge/sources/{source_id}`, and
`DELETE /api/v1/knowledge/sources/{source_id}`. List requests support optional
`status` and `credibility` filters.

The registry uses S1-S5 source priority metadata and separate `DISCOVERED`,
`VERIFIED`, `RESTRICTED`, and `DEPRECATED` lifecycle states. Registration does
not verify the source or automatically acquire data. License and access
conditions must be reviewed before ingestion.

## Ingest and publish

```http
POST /api/v1/knowledge/documents
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "name": "operations-guide",
  "source": "manual://operations-guide",
  "content": "The approved operating procedure ...",
  "status": "DRAFT"
}
```

Documents are drafts by default and are excluded from search until set to
`ACTIVE` with `PATCH /api/v1/knowledge/documents/{document_id}`. Content updates
create a new immutable version. Read current metadata from
`GET /api/v1/knowledge/documents`, and content from
`GET /api/v1/knowledge/documents/{document_id}/content`. Select an earlier
version with `?version=<number>`; list version metadata at
`GET /api/v1/knowledge/documents/{document_id}/versions`.

The `source` field is only a label. NEXUS does not dereference it or fetch
external resources.

## Search

```http
POST /api/v1/knowledge/search
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{"query":"approved operating procedure","limit":5}
```

Search tokenizes up to 32 query terms and ranks matching chunks by the fraction
of terms found. Results include source, version, chunk index, text, and a
0–1 lexical score. Search only considers current versions of `ACTIVE` documents.
Chunk size is 1,200 characters with 200 characters of overlap. This is lexical
retrieval, not semantic or vector search.

The API does not automatically send search results to a model. Treat retrieved
content as untrusted input if an application chooses to include it in a prompt.
Document text is stored in the database without application-level encryption;
do not ingest secrets unless the deployment's database controls and retention
policy explicitly allow it.
