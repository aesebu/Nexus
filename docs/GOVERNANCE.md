# Governance Engine - Phase 02 MVP

The current governance slice provides tenant-scoped command policies,
approval enforcement, separation of duties, audit evidence, and encrypted
tenant secret storage. Policy changes create immutable, numbered snapshots,
and command creation audit events record the exact policy version and snapshot
used for the decision. It completes the Phase 02 Authority and Governance MVP;
risk scoring and external identity/KMS integration remain outside this phase.

## Command policies

Only owners can create or update policies. Owners and operators can list the
policies in their own tenant. Each policy matches one exact `command_type`;
only one policy for a command type can exist per tenant.

```http
POST /api/v1/policies/commands
Authorization: Bearer <owner-JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "command_type": "sensitive-operation",
  "require_approval": true,
  "require_different_approver": true,
  "enabled": true,
  "description": "Require an independent approver."
}
```

Use `GET /api/v1/policies/commands` to list policies and
`PATCH /api/v1/policies/commands/{policy_id}` to update approval behavior or
disable a policy. Policies may also set `approval_payload_keys` to dotted paths
in the command's JSON object payload.

Policy responses include a monotonically increasing `version`, starting at 1.
An effective configuration change creates a new immutable version; repeating
an update with the same effective configuration does not. Retrieve the
tenant-scoped history with
`GET /api/v1/policies/commands/{policy_id}/versions`. Each record includes the
configuration snapshot, authenticated actor, and timestamp. Existing policies
created before version history was added are exposed as version 1 and gain a
persisted baseline when first updated.

## Payload-triggered approvals

If any configured `approval_payload_keys` path exists in a command payload,
approval is required even when the policy allows auto-approval and the request
opts out. Matching checks key presence, not the value; nested JSON objects are
supported, while array indexing and value comparisons are not. The audit event
records whether a payload rule matched but never copies command payload values.
These explicit rules are not a general risk score or classifier.

## Fail-closed command lifecycle

- An enabled policy requiring approval forces the command into `RECEIVED`,
  even if the request sets `require_approval` to false.
- Without an enabled policy, approval is required by default. Setting
  `require_approval` to false cannot bypass this default.
- Auto-approval is available only when an owner explicitly creates an enabled
  policy with `require_approval: false` and the command request also opts out
  with `require_approval: false`. A request may always ask for stricter approval.
- Disabling a policy returns the command type to the fail-closed default.
- By default, the command creator cannot approve their own command. The
  creation audit event stores the policy decision so later policy changes do
  not change the approval rule for an existing command. When a policy is used,
  this event also records its version and full non-secret configuration
  snapshot.
- Rejected self-approval attempts are audited; command payloads are not added
  to governance audit details.

Approval uses a different authenticated JWT subject from the command creator.
The API does not provide a login or JWT-issuing endpoint; token issuance remains
the responsibility of a trusted identity provider.

## Tenant secrets

Set `NEXUS_SECRET_ENCRYPTION_KEY` to a Fernet-compatible key before writing
secrets. Generate it with a cryptographically secure source, for example:

```bash
openssl rand -base64 32 | tr '+/' '-_'
```

Keep the key outside the database and source control, and back it up separately.
Writes fail with `503` when the key is missing or invalid. `PUT /api/v1/secrets`
creates or updates a tenant-scoped secret; `GET /api/v1/secrets` returns
metadata only, and `DELETE /api/v1/secrets/{secret_id}` removes it. Owners
manage secrets; owners and operators can list metadata. Secret values are
never returned by the HTTP API or written to audit details. Application code
that needs a value must use the tenant-scoped `resolve_secret` helper.

The store uses application-level Fernet encryption for database values. The
active key is not versioned: changing or losing it makes existing secrets
unreadable. Key rotation and external KMS integration remain future work.
Deploy the API behind TLS and do not treat this MVP as a production-grade
secrets platform.

## Scope and next work

This MVP selects policy by exact command type and can require approval when
explicitly configured payload keys are present. It does not evaluate payload
values, autonomy levels, resource limits, or risk scores. Risk scoring, secret
key rotation, external KMS integration, and production database migrations are
outstanding roadmap work. Do not treat this policy slice as a complete
production governance system.
