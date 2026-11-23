# NEXUS

**Supreme AI Intelligence — Independent Master Blueprint**

---

## Overview

NEXUS is an advanced artificial intelligence system designed to serve as the central authority for directing, analyzing, deciding, managing, and controlling all AI systems and operating systems within the platform. It is an independent system that connects to AI Models, AI Agents, Applications, Databases, and External Services through a unified, standardized central structure.

## Document Status

| Field | Value |
|---|---|
| Document ID | NEXUS-SAI-MB-001 |
| Version | 1.0 |
| Status | DRAFT |
| Implementation Status | IN PROGRESS |
| Approval Status | PENDING |
| Project Origin | Independent Greenfield |
| External / Legacy Dependency | NONE |

## Architecture at a Glance

NEXUS is built on a three-tier intelligence architecture:

| Tier | Role |
|---|---|
| **Level 1 — NEXUS** | Supreme Intelligence Authority: strategy, goals, planning, decisions |
| **Level 2 — NEXUS CORE** | Central processing and control: models, agents, data, workflows |
| **Level 3 — NEXUS SYSTEM** | Execution and operational environment: agents, workers, integrations |

## Authority Model

```
LEVEL 0  Human Owner        Supreme governing authority
LEVEL 1  NEXUS              Sets direction and makes decisions
LEVEL 2  NEXUS CORE         Controls and coordinates
LEVEL 3  System Directors   Administer subsystems
LEVEL 4  AI Agents          Perform operations
LEVEL 5  Tools              Perform specialized actions
```

Autonomy levels run from **L0 Read Only** through **L5 Strategic Autonomous Operations**, always bounded by defined Policy and Permission.

## Core Modules

| Module | Purpose |
|---|---|
| CORE-01 | Control Engine — central control |
| CORE-02 | AI Engine — inference and context |
| CORE-03 | Model Intelligence — model registry and routing |
| CORE-04 | Agent Engine — agent lifecycle and orchestration |
| CORE-05 | Memory & Knowledge Engine — memory layers and knowledge graph |
| CORE-06 | Intelligence Engine — reasoning and decision support |
| CORE-07 | Automation Engine — workflows and scheduling |
| CORE-08 | Data & Administration — data, identity, tenants, audit |
| CORE-09 | Security & Governance — access control, policy, secrets |

## Proposed Technology Baseline

| Layer | Technology |
|---|---|
| Frontend | React / TypeScript |
| Backend | Python / FastAPI |
| Database | PostgreSQL |
| ORM / Migration | SQLAlchemy / Alembic |
| API | REST |
| Authentication | JWT / RBAC |
| Vector Database | pgvector |
| Containerization | Docker |
| Version Control | Git |
| Testing | Pytest |

Architecture style: **Modular Monolith** first, designed for future separation into Microservices.
Deployment: supports **Local, Cloud, and Hybrid**, with a Control Plane / Execution Plane split and multi-tenant isolation.

## Development Roadmap

| Phase | Focus | Deliverable | Status |
|---|---|---|---|
| 00 | Project Foundation | Project Specification | Complete (validated) |
| 01 | Supreme Architecture | Architecture Specification | Complete (validated) |
| 02 | Authority & Governance | Governance Engine | Complete (validated) |
| 03 | Core Foundation | Central Control | Complete (MVP) |
| 04 | AI Infrastructure | Model Intelligence | Complete (validated) |
| 05 | AI Engine | Inference Engine | Partial |
| 06 | Agent Intelligence | Agent Engine | Planned |
| 07 | Memory & Knowledge | Knowledge Platform | Planned |
| 08 | Intelligence Engine | Reasoning & Decision Support | Planned |
| 09 | Automation | Workflow Engine | Planned |
| 10 | NEXUS System | Operational Ecosystem | Planned |
| 11 | Integration | Integrated Platform | Planned |
| 12 | Production | Production Release | Planned |
| 13 | Evolution | Continuous Improvement | Planned |

## Repository Contents

| File | Description |
|---|---|
| [`NEXUS_Master_Blueprint_EN.md`](NEXUS_Master_Blueprint_EN.md) | Full master blueprint (English), covering all 13 sections |
| [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) | Command policy and approval enforcement MVP |
| [`docs/AI_ENGINE.md`](docs/AI_ENGINE.md) | AI inference, provider setup, registry, and authorization guide |
| [`docs/PHASE_00_PROJECT_FOUNDATION.md`](docs/PHASE_00_PROJECT_FOUNDATION.md) | Phase 00 specification, implementation, acceptance criteria, and test evidence |
| [`docs/PHASE_01_SUPREME_ARCHITECTURE.md`](docs/PHASE_01_SUPREME_ARCHITECTURE.md) | Phase 01 three-tier architecture, boundaries, flows, deployment, and acceptance criteria |
| [`docs/PHASE_02_AUTHORITY_AND_GOVERNANCE.md`](docs/PHASE_02_AUTHORITY_AND_GOVERNANCE.md) | Phase 02 authority model, governance decisions, audit evidence, and acceptance criteria |
| [`examples/nexus-api.http`](examples/nexus-api.http) | Sample model registry and inference requests |
| [`examples/seed_models.json`](examples/seed_models.json) | Disabled placeholder models for optional development seeding |

## Development Governance

```
PLANNED → DRAFT → REVIEW → APPROVED → DEVELOPMENT → TESTING → VALIDATED → RELEASED
```

A module must never be declared complete without test evidence. Every change must record a Change ID, Version, Reason, Impact Analysis, Approval, and Test Evidence.

## MVP Implementation Status

The initial implementation provides:

- FastAPI modular monolith foundation
- SQLite development database and PostgreSQL deployment configuration
- JWT bearer authentication with tenant and role permissions
- Command lifecycle with approval and execution states
- Tenant-scoped audit events
- Emergency stop activation and clearing
- Tenant-scoped command policies with fail-closed defaults and payload-key approval rules
- Separate creator/approver enforcement, immutable policy version history, and command decision snapshots
- Tenant-scoped system registry with owner-managed lifecycle status
- Tenant-scoped manual task lifecycle and durable AI inference worker queue
- Event journal with source validation, filters, and audit records
- Tenant-scoped configuration store for non-secret values
- Tenant-scoped encrypted secret store with metadata-only API responses
- Tenant-scoped AI model registry
- Capability and provider-aware deterministic model routing
- Model lifecycle status and priority configuration
- OpenAI-compatible chat inference
- NEXUS assistant chat endpoint with a fixed identity prompt and request-scoped context
- Opt-in development model seed data
- Docker and Docker Compose configuration
- Pytest API coverage

## Deployment security

Production deployments must set:

- `NEXUS_ENVIRONMENT=production`
- `NEXUS_DATABASE_URL`
- `NEXUS_JWT_SECRET` with at least 32 characters
- `NEXUS_JWT_ISSUER`
- `NEXUS_JWT_AUDIENCE`
- `NEXUS_SECRET_ENCRYPTION_KEY`

The application refuses to start in production when the JWT configuration is
missing or uses the development JWT secret. Production JWTs must include
`exp`, `iss`, and `aud`. Docker Compose requires `POSTGRES_PASSWORD` and
`NEXUS_JWT_SECRET` from the deployment environment.

Database schema changes are managed by Alembic:

```bash
alembic upgrade head
alembic downgrade base
```

The API container and worker both apply migrations before startup. The legacy
development startup path may create missing SQLite tables, but production
startup does not use `create_all()`.

Use `/health/live` for process liveness and `/health/ready` for database
readiness. `/health` remains available as a compatibility endpoint.

Manual tasks continue to use the task lifecycle endpoints. Tasks created with
`work_type: "ai.inference"` are claimed by the separate worker process, routed
to an enabled chat model for the same tenant, and completed with a JSON
`InferenceResponse` in the task's `result`. Configure an enabled chat model and
`NEXUS_AI_API_KEY` before submitting inference tasks. The worker uses database
leases and retries transient provider failures up to three attempts; processing
is at-least-once, so a provider timeout can cause a repeated request. Emergency
stop prevents new tasks from being claimed. Inference prompts and results are
stored unencrypted in the application database; results are visible through
tenant-scoped task reads, so do not include secret values. The event journal
stores and filters events but does not dispatch them through a broker. Tenant
configuration values are stored for management but are not automatically
applied to runtime settings; this store is not for credentials or other
secrets. Secret writes require
`NEXUS_SECRET_ENCRYPTION_KEY`; values are encrypted before persistence and are
available to application code through the tenant-scoped resolver, not through
the HTTP API. The encryption key is deployment-managed and not stored in the
database. Key rotation and external KMS support are not implemented.

Start the local API:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
uvicorn app.main:app --reload
```

For local background execution, run the worker in a second terminal:

```bash
python -m app.worker
```

Docker Compose starts the worker alongside the API. To enqueue an inference
task, post a task with `work_type: "ai.inference"` and `work_payload` matching
the `/api/v1/ai/infer` request body.

Run tests:

```bash
pytest
```

## License

Not yet defined.
