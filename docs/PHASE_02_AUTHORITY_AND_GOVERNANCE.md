# Phase 02 - Authority and Governance

| Field | Value |
|---|---|
| Phase | 02 |
| Name | Authority and Governance |
| Deliverable | Governance Engine |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-02 |
| Version | 1.0 |
| Document ID | NEXUS-SAI-MB-001 |

## 1. Specification

Phase 02 defines and validates the first Governance Engine for NEXUS. The engine
must decide whether commands may be auto-approved or require approval, enforce
separation of duties, stop new governed work during an emergency, preserve
decision evidence, and keep governance resources isolated by tenant.

The implementation is a governance MVP. It is not a production risk engine,
external policy decision service, or complete identity system.

## 2. Authority Model

| Level | Authority represented by the MVP |
|---|---|
| Human owner | Creates governance policy and controls emergency stop |
| NEXUS | Applies fixed architecture and policy decision rules |
| NEXUS CORE | Resolves permission, policy, tenant, and lifecycle state |
| System or operator | Creates, executes, reads, or cancels commands when permitted |
| Tool or provider | Executes only within an API-approved context |

JWT roles and tenant claims are the identity inputs. The API does not issue
tokens or provide a local user/identity database.

## 3. Governance Components

| Component | Implementation | Purpose |
|---|---|---|
| Permission enforcement | `app/security.py` | Role and permission checks |
| Tenant enforcement | JWT tenant claim + `X-Tenant-ID` | Tenant isolation |
| Command policies | `CommandPolicy` models and policy routes | Decision configuration |
| Payload trigger rules | `CommandPolicyPayloadRule` | Presence-based approval escalation |
| Immutable policy history | `CommandPolicyVersion` | Reproducible effective configuration |
| Command lifecycle | `Command` model and command routes | Governed execution state |
| Audit trail | `AuditEvent` model and `/audit` | Tenant-visible operational evidence |
| Emergency stop | `EmergencyStop` model and routes | Halt command and inference activity |
| Secret custody | `TenantSecret` and `app/secrets.py` | Fernet-encrypted tenant values |

## 4. Decision Rules

The effective command decision follows these rules:

1. An active emergency stop blocks command creation and execution.
2. An enabled exact command-type policy is resolved within the tenant.
3. A configured payload path is matched by key presence, including nested
   dotted object paths.
4. Approval is required when the request asks for it, no enabled policy exists,
   the policy requires approval, or a payload rule matches.
5. Approval is denied for the creator when the creation decision requires a
   different approver.
6. A policy update takes effect for later commands; existing command decision
   evidence is retained from creation.
7. Disabling or removing an effective policy's approval behavior does not
   silently relax the fail-closed default.

The policy engine is deterministic and does not infer values, scores, risk,
autonomy levels, or resource limits.

## 5. Separation of Duties

Policy management is restricted to the `owner` role. Policy reads are available
to owners and operators. Command approval and execution are separate API actions
and require their declared permissions.

When `require_different_approver` is true for the effective creation decision,
the command creator cannot approve the command, even if the creator is a
different authenticated subject from the policy actor.

No client-supplied approver identity is accepted. Approval identity comes only
from the authenticated JWT subject.

## 6. Policy Versioning

Every policy change that alters effective behavior creates a monotonically
increasing version. Repeated no-op updates do not create a new version.

Each version stores:

- Command type
- Approval requirement
- Different-approver requirement
- Enabled state
- Description
- Sorted approval payload paths
- Authenticated changing actor
- Creation timestamp

The command creation audit event stores the effective policy identifier,
version, and snapshot when a policy is used. Later policy changes cannot change
the evidence recorded for an existing command.

Legacy policies without persisted versions receive a baseline version of 1 when
queried or updated.

## 7. Audit and Emergency Evidence

Governance audit events are tenant-scoped and include actor, action, resource,
outcome, detail, and timestamp.

The audit trail covers policy creation and updates, command creation and
approval decisions, self-approval rejection, command execution/cancellation,
secret operations, emergency stop activation and clearing, and selected control
operations.

Audit details must not include command payload values or secret values.

The emergency stop state is tenant-scoped. It prevents command creation,
command approval and execution, AI inference, and queued task claiming. Clearing
the state requires an authenticated owner permission and is independently
audited.

## 8. Tenant Isolation

Every governance query must use tenant ID in addition to resource ID. Policy,
command, audit, secret, and emergency-stop resources are tenant-scoped.

Cross-tenant resource lookups return not-found or unauthorized outcomes rather
than exposing the existence of a resource.

## 9. Scope and Future Work

Included in the Phase 02 MVP:

- Tenant-scoped roles and permissions
- Fail-closed command defaults
- Exact command-type policies
- Payload-key approval escalation
- Immutable policy versions
- Creator/approver separation
- Tenant audit records
- Emergency stop
- Encrypted tenant secret storage

Explicitly outside the Phase 02 MVP:

- General identity issuance or identity database
- Signed policy bundles and external policy engines
- Risk scores and machine-learning classifications
- Autonomy-level authorization
- Resource and quota enforcement
- Secret key rotation and external KMS
- Tamper-proof external audit retention
- Cross-region or cross-tenant policy inheritance

These are future enhancements and must not be represented as implemented.

## 10. Acceptance Criteria

| ID | Criterion | Evidence |
|---|---|---|
| AG-01 | Governance scope and authority model are documented | Sections 1-3 |
| AG-02 | Policy decisions are deterministic and fail closed | Command creation tests |
| AG-03 | Payload presence rules trigger approval | Payload policy tests |
| AG-04 | Creator and approver separation is enforced | Separate-subject tests |
| AG-05 | Policy updates create immutable versions | Version and legacy-policy tests |
| AG-06 | Governance resources are tenant-scoped | Cross-tenant tests |
| AG-07 | Emergency stop blocks governed operations | Stop and worker tests |
| AG-08 | Sensitive payload and secret values are not added to audit details | Audit assertions |
| AG-09 | Governance behavior has executable test coverage | Pytest suite |

## 11. Test Evidence

Run:

```bash
./.venv/bin/pytest -q
```

The suite validates the implementation as a governance MVP, including tenant
isolation, fail-closed decisions, approval separation, policy history, payload
rules, secret metadata behavior, and emergency stop.

## 12. Reason and Impact Analysis

Reason:

- Complete Phase 02 around an implemented, reviewable Authority and Governance
  engine without overstating future risk and identity capabilities.

Impact:

- Establishes governance behavior and boundaries for later execution phases.
- Reuses existing command, policy, audit, emergency-stop, and secret models.
- Does not add a new runtime risk classifier or external identity provider.

## 13. Approval and Change Record

- Implementation: complete for the documented MVP
- Testing: complete
- Validation: complete
- Human owner approval: pending where formal organizational approval is required
