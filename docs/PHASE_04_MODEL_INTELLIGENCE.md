# Phase 04 - AI Infrastructure and Model Intelligence

| Field | Value |
|---|---|
| Phase | 04 |
| Name | AI Infrastructure / Model Intelligence |
| Deliverable | Model registry, routing, discovery, and health evidence |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-04 |
| Version | 1.0 |

## Specification

Phase 04 extends the tenant-scoped model registry with provider catalog discovery
and runtime health evidence. Registry status, capability declarations, priority,
and routing remain administrative and deterministic. Provider discovery verifies
whether model identifiers appear in the provider catalog.

## Components

| Component | Implementation | Purpose |
|---|---|---|
| Registry | `AIModel` | Tenant-owned model metadata |
| Routing | `POST /api/v1/models/route` | Deterministic capability/provider selection |
| Discovery | `GET /api/v1/models/catalog/discover` | Read provider model identifiers |
| Health evidence | `POST /api/v1/models/{model_id}/health` | Catalog availability probe |
| Audit | `AuditEvent` | Discovery and health evidence |

## Health semantics

- `UNKNOWN` is the initial state.
- `HEALTHY` means the model identifier was present in a successful provider catalog response.
- `UNHEALTHY` means the identifier was absent or the provider probe failed.
- A registry status of `ENABLED` does not imply a healthy runtime.
- Health is evidence, not a guarantee that every inference response will succeed.

## Boundaries

The MVP supports discovery for `openai-compatible` providers. It does not add
provider model auto-registration, continuous polling, inference benchmarks,
quota monitoring, cost monitoring, or external model evaluators.

## Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| MI-01 | Provider catalog discovery is tenant-authenticated | API tests |
| MI-02 | Catalog results are deduplicated and sorted | Provider tests |
| MI-03 | Model health is separate from registry status | Model response fields |
| MI-04 | Health checks update tenant-scoped model evidence | API tests |
| MI-05 | Discovery and health failures produce audit evidence | Provider/API tests |
