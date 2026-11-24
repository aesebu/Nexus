# Phase 12 — Production Release

## Goal

Provide a repeatable, fail-closed container deployment path for the NEXUS
production MVP, with database migrations completed before application
processes start and automated checks for the migration lifecycle.

## MVP scope

- Production settings require a strong JWT secret, issuer, audience, and valid
  secret-encryption key.
- Docker images run the API, worker, and migration process as an unprivileged
  user.
- Docker Compose waits for PostgreSQL readiness, runs one migration job, and
  starts API and worker only after that job succeeds.
- API readiness checks database connectivity; liveness remains independent of
  database availability.
- The worker records a database heartbeat, exposes health through
  `/health/worker`, and has a Docker Compose health probe. Production worker
  startup relies on the migration job rather than `create_all()`.
- CI runs compilation and tests and exercises migration upgrade, downgrade,
  and re-upgrade on SQLite.
- Deployment documentation states required secrets, TLS boundary, worker
  semantics, and data-recovery responsibilities.

## Release procedure

1. Provide `POSTGRES_PASSWORD`, `NEXUS_JWT_SECRET`,
   `NEXUS_SECRET_ENCRYPTION_KEY`, and the production JWT issuer/audience.
2. Set `NEXUS_INTEGRATION_ALLOWED_HOSTS` to exact allowed webhook hostnames
   when webhook delivery is required.
3. Run `docker compose up --build`; Compose waits for PostgreSQL, runs
   `alembic upgrade head` once, then starts the API and worker.
4. Confirm the API `/health/ready` endpoint reports ready and review CI
   migration and test results before release.
5. Place the API behind a TLS-terminating reverse proxy. Keep secrets and
   database backups outside the image and source repository.

## Acceptance criteria

- API and worker do not race to apply schema changes during startup.
- A failed migration prevents the API and worker from starting.
- The application image does not run as root.
- The worker heartbeat is refreshed at startup and at least every ten seconds
  while idle; missing or stopped workers are reported unhealthy.
- `/health/ready` remains a database-readiness check and does not imply worker
  health.
- Required production configuration is validated before serving requests.
- CI verifies reversible migration history and the complete test suite.

## Explicit exclusions and operational limits

- This repository does not provision a production orchestrator, TLS
  certificates, external secret manager, centralized telemetry, or managed
  backup service.
- Operators must configure, encrypt, retain, and test database backups and
  separately back up the tenant secret-encryption key. Losing that key makes
  existing encrypted secrets unreadable.
- Database migrations are run as the application database role, which needs
  schema-change privileges; use a separately managed role if the deployment
  platform supports distinct migration and runtime credentials.
- Task and webhook processing is at-least-once. Monitor worker health and
  account for duplicate side effects.
- Production readiness of the API does not imply that AI providers, workers,
  webhooks, or external dependencies are healthy. Query `/health/worker` or
  inspect the Compose worker health status for worker process liveness; the
  heartbeat is considered stale after six minutes.

## Status

Complete (MVP). The release path is containerized and CI-validated; external
production infrastructure and operational controls remain deployment
responsibilities.
