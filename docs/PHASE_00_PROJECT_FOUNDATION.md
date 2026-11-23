# Phase 00 - Project Foundation

| Field | Value |
|---|---|
| Phase | 00 |
| Name | Project Foundation |
| Deliverable | Project Specification |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-00 |
| Version | 1.0 |
| Document ID | NEXUS-SAI-MB-001 |

## 1. Specification

NEXUS is an independent greenfield system that provides a centralized authority
for planning, governing, coordinating, and operating AI models and agents.

The initial implementation follows a modular-monolith architecture:

- Backend: Python and FastAPI
- Data: SQLite for local development and PostgreSQL for deployment
- ORM and migrations: SQLAlchemy and Alembic
- API: versioned REST API under `/api/v1`
- Authentication: JWT bearer tokens
- Authorization: tenant-scoped roles and policy enforcement
- Containers: Docker and Docker Compose
- Testing: Pytest
- Documentation: repository Markdown specifications and API examples

The foundation defines these initial platform boundaries:

1. A human owner remains the supreme governing authority.
2. Commands require authentication, tenant scope, role permissions, and policy
   approval where applicable.
3. The platform must provide audit evidence for management and operational
   actions.
4. Tenant data and credentials must remain isolated.
5. Deployment secrets must come from environment or deployment-managed
   configuration, not source control.
6. The system must support local, containerized, and future hybrid deployment.
7. Implemented behavior must be represented in executable tests.

## 2. Repository Implementation

The foundation implementation includes:

- [NEXUS master blueprint](../NEXUS_Master_Blueprint_EN.md)
- FastAPI application entry point and `/health` endpoint
- Versioned API router
- Tenant-scoped application models and schemas
- JWT and tenant authorization helpers
- SQLAlchemy database configuration
- Environment-based configuration and secret handling
- Docker and Docker Compose deployment configuration
- Governance and AI-engine documentation
- HTTP API examples and development model seed data
- Pytest fixtures and API coverage

## 3. Required Configuration

Development configuration is documented in `.env.example`.

Required for normal operation:

- `NEXUS_DATABASE_URL`
- `NEXUS_JWT_SECRET`
- `NEXUS_JWT_ALGORITHM`

Optional or deployment-dependent:

- `NEXUS_SECRET_ENCRYPTION_KEY`
- `NEXUS_AI_BASE_URL`
- `NEXUS_AI_API_KEY`

The default JWT secret must be replaced outside development. Secret values must
not be committed to the repository.

## 4. Acceptance Criteria

Phase 00 is accepted when all of the following are true:

| ID | Criterion | Evidence |
|---|---|---|
| PF-01 | Project scope and architecture are documented | Master blueprint and this specification |
| PF-02 | Repository has a runnable FastAPI foundation | `app/main.py` and `/health` |
| PF-03 | Dependencies and supported Python version are declared | `pyproject.toml` |
| PF-04 | Environment configuration has an example | `.env.example` |
| PF-05 | Local and container execution are defined | README, Dockerfile, and Docker Compose |
| PF-06 | Database initialization is implemented | SQLAlchemy models and application lifespan |
| PF-07 | Authentication and tenant context are implemented | JWT and tenant authorization helpers |
| PF-08 | Governance and change rules are documented | Master blueprint and governance documentation |
| PF-09 | API behavior has executable test coverage | Pytest suite |
| PF-10 | Foundation test evidence passes | 46 tests passed |

## 5. Test Evidence

Run the foundation suite from the repository root:

```bash
./.venv/bin/pytest -q
```

Latest validated result:

```text
46 passed, 1 warning
```

The warning is a Starlette deprecation notice for `httpx` test-client integration
and does not fail the suite.

## 6. Reason and Impact Analysis

Reason:

- Establish one complete, reviewable project-foundation baseline before Phase 01
  architecture work proceeds.

Impact:

- Provides requirements, repository structure, configuration, execution,
  governance, and acceptance evidence for subsequent phases.
- Does not alter runtime behavior.

## 7. Approval and Change Record

Approval status:

- Implementation: complete
- Testing: complete
- Validation: complete
- Human owner approval: pending where formal approval is required by repository
  governance

No phase may be declared complete without test evidence. This foundation
remains test-validated while awaiting any additional organizational approval.
