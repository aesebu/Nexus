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
| CORE-05 | Memory & Knowledge Engine — knowledge repository, source registry, and future memory/graph layers |
| CORE-06 | Intelligence Engine — reasoning and decision support |
| CORE-07 | Automation Engine — workflows and scheduling |
| CORE-08 | Data & Administration — data, identity, tenants, audit |
| CORE-09 | Security & Governance — access control, policy, secrets |

## Proposed Technology Baseline

| Layer | Technology |
|---|---|
| Frontend | React / TypeScript |
| Backend | Python / FastAPI |
| Database | SQLite for development; PostgreSQL for deployment |
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
| 05 | AI Engine | Inference Engine | Complete (MVP) |
| 06 | Agent Intelligence | Agent Engine | Complete (MVP) |
| 07 | Memory & Knowledge | Knowledge Repository and Source Registry | Complete (MVP) |
| 08 | Intelligence Engine | Reasoning & Decision Support | Complete (MVP) |
| 09 | Automation | Workflow Engine | Complete (MVP) |
| 10 | NEXUS System | Operational Ecosystem | Complete (MVP) |
| 11 | Integration | Integrated Platform | Complete (MVP) |
| 12 | Production | Production Release | Complete (MVP) |
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
| [`docs/PHASE_05_AI_ENGINE.md`](docs/PHASE_05_AI_ENGINE.md) | Phase 05 AI Engine specification, implementation, boundaries, and acceptance criteria |
| [`docs/PHASE_06_AGENT_ENGINE.md`](docs/PHASE_06_AGENT_ENGINE.md) | Phase 06 agent registry, lifecycle, orchestration, security boundaries, and acceptance criteria |
| [`docs/AGENT_ENGINE.md`](docs/AGENT_ENGINE.md) | Agent Engine API and operations guide |
| [`docs/PHASE_07_MEMORY_KNOWLEDGE.md`](docs/PHASE_07_MEMORY_KNOWLEDGE.md) | Phase 07 knowledge repository, source registry, lexical retrieval, security boundaries, and acceptance criteria |
| [`docs/KNOWLEDGE_ENGINE.md`](docs/KNOWLEDGE_ENGINE.md) | Knowledge Engine API and operations guide |
| [`docs/PHASE_08_INTELLIGENCE_ENGINE.md`](docs/PHASE_08_INTELLIGENCE_ENGINE.md) | Phase 08 deterministic decision-support specification, rules, and acceptance criteria |
| [`docs/INTELLIGENCE_ENGINE.md`](docs/INTELLIGENCE_ENGINE.md) | Intelligence Engine API and operations guide |
| [`docs/PHASE_09_AUTOMATION_WORKFLOWS.md`](docs/PHASE_09_AUTOMATION_WORKFLOWS.md) | Phase 09 automation workflow scope, execution semantics, boundaries, and acceptance criteria |
| [`docs/AUTOMATION_WORKFLOWS.md`](docs/AUTOMATION_WORKFLOWS.md) | Automation workflow API and operations guide |
| [`docs/PHASE_10_OPERATIONAL_ECOSYSTEM.md`](docs/PHASE_10_OPERATIONAL_ECOSYSTEM.md) | Phase 10 tenant application registry scope, security boundaries, and acceptance criteria |
| [`docs/APPLICATION_ECOSYSTEM.md`](docs/APPLICATION_ECOSYSTEM.md) | Application registry API and authorization boundary |
| [`docs/PHASE_11_INTEGRATION.md`](docs/PHASE_11_INTEGRATION.md) | Phase 11 signed outbound webhook scope, delivery semantics, security boundaries, and acceptance criteria |
| [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) | Outbound webhook setup, signature verification, retries, and operations |
| [`docs/PHASE_12_PRODUCTION_RELEASE.md`](docs/PHASE_12_PRODUCTION_RELEASE.md) | Phase 12 production deployment scope, release checks, and operational boundaries |
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
- Persistent conversation context, structured JSON output, and tool-call declarations
- NEXUS assistant chat endpoint with a fixed identity prompt and request-scoped context
- Tenant-scoped AI agent registry, lifecycle management, explicit invocation, and bounded orchestration
- Tenant-scoped versioned knowledge documents with lexical chunk retrieval
- Tenant-scoped knowledge source registry with credibility, license, access, verification, and lifecycle metadata
- Deterministic, tenant-scoped weighted decision assessments with separate risk analysis
- Tenant-scoped, versioned AI inference workflows with delayed runs and resumable worker execution
- Tenant-scoped application registry with lifecycle and declared permission/data scopes
- Signed outbound webhook delivery from tenant event subscriptions with allowlisted HTTPS destinations
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

For outbound webhooks, configure `NEXUS_INTEGRATION_ALLOWED_HOSTS` as a
comma-separated list of exact HTTPS destination hostnames. Docker Compose
passes this value to both the API and worker.

The application refuses to start in production when the JWT configuration is
missing or uses the development JWT secret. Production JWTs must include
`exp`, `iss`, and `aud`. Docker Compose requires `POSTGRES_PASSWORD` and
`NEXUS_JWT_SECRET` from the deployment environment.

Database schema changes are managed by Alembic:

```bash
alembic upgrade head
alembic downgrade base
```

Docker Compose runs a one-shot migration service after PostgreSQL is healthy,
then starts the API and worker only if migrations succeed. The legacy
development startup path may create missing SQLite tables, but production
startup does not use `create_all()`.

Use `/health/live` for process liveness and `/health/ready` for database
readiness. `/health` remains available as a compatibility endpoint.

Manual tasks continue to use the task lifecycle endpoints. Tasks created with
`work_type: "ai.inference"`, active automation workflow runs, and webhook
deliveries are claimed by the separate worker process. Configure an enabled
chat model and `NEXUS_AI_API_KEY` before submitting inference work. Webhook
delivery requires an allowlisted hostname and a signing secret in the tenant
secret store. The worker uses database leases and retries transient failures
up to three attempts; processing is at-least-once, so a provider timeout can
cause a repeated request. Workflow runs snapshot their definition and persist
each completed step to resume after retries. Emergency stop prevents new tasks
from being claimed. Inference prompts, workflow inputs, and results are stored
unencrypted in the application database; results are visible through
tenant-scoped reads, so do not include secret values. The event journal stores
and filters events, then queues matching webhook deliveries through the worker
without using a separate event broker. Tenant
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

Docker Compose runs a one-shot migration service after PostgreSQL is healthy,
then starts the API and worker only if migrations succeed. Application
containers run as an unprivileged user. Place the API behind a TLS-terminating
reverse proxy for external access. To enqueue an inference task, post a task with `work_type: "ai.inference"` and
`work_payload` matching the `/api/v1/ai/infer` request body. For workflows,
create and activate one through `/api/v1/workflows`, then queue a run through
`/api/v1/workflows/{workflow_id}/runs`.

Run tests:

```bash
pytest
```

## License

Not yet defined.
