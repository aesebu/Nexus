# Phase 10 — NEXUS Operational Ecosystem

## Goal

Provide a tenant-scoped application registry for the operational ecosystem.
Each registered application has a stable key, lifecycle status, and explicit
declarations of the NEXUS permission and data scopes it expects.

## MVP scope

- Register, list, read, and update application profiles.
- Enforce tenant-local uniqueness for application keys and scope every lookup
  by the authenticated tenant.
- Validate declared permission scopes against permissions currently known to
  NEXUS and validate data-scope identifiers.
- Support `REGISTERED`, `ENABLED`, and `DISABLED` metadata states.
- Record lifecycle changes in the tenant audit log without copying scope
  values into audit details.

## API

- `POST /api/v1/applications`
- `GET /api/v1/applications?status=ENABLED&limit=100&offset=0`
- `GET /api/v1/applications/{application_id}`
- `PATCH /api/v1/applications/{application_id}`

`nexus.application.manage` is restricted to owners. Owner, operator, and
viewer roles can read with `nexus.application.read`. App keys are immutable
after creation; a different key requires a new application record.

## Security boundary

An application profile is administrative metadata, not an authenticated
principal or credential. Declared permissions and data scopes do not alter
`require_permission`, issue tokens, grant the application or its users access,
or constrain data queries. Existing user JWTs and role-based authorization
remain authoritative. Credential lifecycle, app-specific authentication, and
runtime enforcement of app scopes are explicitly out of this phase.

## Acceptance

- Duplicate application keys conflict within a tenant but may exist in
  different tenants.
- Cross-tenant reads return not found.
- Only owners can create or update records; all roles can read.
- Unknown permission scopes, malformed data scopes, duplicates, null
  non-nullable update fields, and empty updates are rejected.
- Audit events record application creation/update and scope counts without
  logging scope values.
