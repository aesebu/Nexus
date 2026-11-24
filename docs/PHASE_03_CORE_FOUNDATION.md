# Phase 03 — Core Foundation

| Field | Value |
|---|---|
| Phase | 03 |
| Name | Core Foundation |
| Deliverable | Central Control |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-03 |
| Version | 1.0 |
| Document ID | NEXUS-SAI-MB-001 |

## 1. Specification

Provide the central API and durable control records used to register systems,
receive commands, manage manual tasks, journal events, and store tenant
configuration. Every resource is scoped to the authenticated tenant; lifecycle
and sensitive operations are authorized and audited.

The Phase 03 deliverable is the control-plane foundation. Governance rules are
specified in [Phase 02](./PHASE_02_AUTHORITY_AND_GOVERNANCE.md), AI and model
management in [Phase 04](./PHASE_04_MODEL_INTELLIGENCE.md), and production
container/migration behavior in
[Phase 12](./PHASE_12_PRODUCTION_RELEASE.md).

## 2. Components

| Component | Implementation | Responsibility |
|---|---|---|
| Versioned API | `app/main.py`, `app/api/routes.py` | Expose tenant-scoped control endpoints under `/api/v1` |
| Command control | `Command`, command routes | Persist command state, enforce lifecycle transitions, and record audit evidence |
| System registry | `SystemRegistration` | Maintain tenant-owned system profiles and lifecycle status |
| Task control | `ControlTask` and task routes | Manage manual task lifecycle |
| Durable work queue | `TaskWorkItem`, `app/worker.py` | Lease, execute, retry, and record supported background work |
| Event journal | `ControlEvent` and event routes | Validate, persist, filter, and audit tenant events |
| Tenant configuration | `TenantConfiguration` and configuration routes | Store non-secret tenant values for management |
| Persistence and health | `app/core/database.py`, `app/main.py` | Persist control state and expose liveness/readiness checks |

## 3. Boundaries

- JWT identity and tenant claims are supplied by the deployment; NEXUS does
  not issue identity credentials.
- Command policy decisions, approval separation, and emergency-stop governance
  are defined by Phase 02.
- Manual tasks use explicit lifecycle endpoints. Only supported queued work
  types are executed by the worker; arbitrary code is not executed.
- The event journal is not a general-purpose message broker. Signed outbound
  webhook delivery is specified separately in
  [Phase 11](./PHASE_11_INTEGRATION.md).
- Tenant configuration is not a secret store and is not automatically applied
  to runtime settings. Secret custody is governed by Phase 02.
- Runtime metrics, centralized monitoring, automatic configuration reload,
  and high availability are outside this MVP.

## 4. Acceptance criteria and evidence

| ID | Criterion | Evidence |
|---|---|---|
| CF-01 | API routes are versioned and health/readiness endpoints are available | `tests/test_architecture_phase01.py::test_versioned_api_composition_is_present`; `tests/test_api.py::test_health`; `test_liveness_and_readiness` |
| CF-02 | Commands follow lifecycle rules, are tenant-isolated, and create audit records | `tests/test_api.py::test_command_lifecycle_and_audit`; `test_tenant_isolation`; `test_cancel_command_lifecycle` |
| CF-03 | System registrations are tenant-scoped and owner-managed | `tests/test_api.py::test_system_registry_is_tenant_scoped_and_owner_managed`; `test_system_registry_rejects_operator_write_and_null_capabilities` |
| CF-04 | Manual tasks are lifecycle-managed; supported queued work is retried and respects emergency stop | `tests/test_api.py::test_task_lifecycle_and_audit`; `test_ai_inference_task_runs_through_background_worker`; `test_worker_retries_transient_inference_failure`; `test_worker_rejects_invalid_jobs_and_honors_emergency_stop` |
| CF-05 | Events are journaled and filtered only after source validation; invalid sources and oversized payloads are rejected | `tests/test_api.py::test_event_journal_filters_events_and_validates_enabled_source`; `test_event_journal_rejects_unavailable_sources_and_oversized_payloads` |
| CF-06 | Tenant configuration is isolated, manageable by authorized roles, and rejects secret-like keys | `tests/test_api.py::test_tenant_configuration_upsert_access_and_delete`; `test_tenant_configuration_rejects_secret_keys_and_invalid_values` |
| CF-07 | The control API and persistence behavior pass the project test suite | `tests/test_api.py`; `tests/test_architecture_phase01.py` |

## 5. Status

Validated (MVP). The acceptance evidence is maintained in the linked API and
architecture tests; production release constraints are documented separately
in Phase 12.
