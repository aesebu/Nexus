# Application Ecosystem

The application registry stores tenant-scoped application profiles. It is
intended to make application ownership and requested access scopes explicit
before later integration and authentication work.

## Create an application profile

```json
{
  "app_key": "case-dashboard",
  "name": "Case Dashboard",
  "description": "Tenant case-management interface",
  "permission_scopes": [
    "nexus.task.read",
    "nexus.workflow.read"
  ],
  "data_scopes": [
    "cases.read",
    "workflows.read"
  ]
}
```

Send this payload to `POST /api/v1/applications` using an owner token. New
profiles default to `REGISTERED`; owners can update the status to `ENABLED` or
`DISABLED`. App keys are lowercase kebab-case identifiers, unique within a
tenant, and immutable. Permission scope values must match permissions already
defined by NEXUS. Data scopes are validated identifiers and are otherwise
application-defined.

Use `GET /api/v1/applications` to list profiles; it supports optional `status`,
`limit`, and `offset` query parameters. `GET /api/v1/applications/{id}` reads a
profile. `PATCH /api/v1/applications/{id}` updates its name, description,
status, or declared scopes. Owners can manage profiles; all roles have
read-only access.

## Important authorization boundary

Application records and their scopes are declarations only. An `ENABLED`
status does not authenticate an application or grant any permissions.
`permission_scopes` and `data_scopes` are not consulted by request
authorization or data access. The current user JWT and role permission map
remain authoritative. This phase does not create application credentials,
issue tokens, or implement per-application runtime authorization.

Audit records include the application key, changed field names, and scope
counts, but omit the scope values.

See the [Phase 10 specification](./PHASE_10_OPERATIONAL_ECOSYSTEM.md) for
acceptance criteria and exclusions.
