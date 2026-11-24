# Phase 09 — Automation Workflows

## Goal

Provide a durable, tenant-scoped MVP for defining and manually scheduling
ordered AI inference workflows. Workflow execution uses the existing database
worker queue, leases, retries, model registry, permissions, and emergency stop.

## Scope

- Create, list, read, and update workflows with `DRAFT`, `ACTIVE`, and
  `INACTIVE` lifecycle states.
- Define 1–10 ordered inference steps. Each step has its own prompt, optional
  system prompt/provider/JSON response format, and optional equality condition.
- Run active workflows immediately or schedule a single delayed start up to 30
  days in the future.
- Evaluate conditions against the run's input JSON only. Conditions use a
  dotted object path and equality comparison; a missing path is a non-match.
- Snapshot the workflow version and steps when a run is queued. Later edits
  affect new runs only.
- Persist each completed or skipped step before continuing, so a worker retry
  resumes at the first unfinished step.
- Expose run state, per-step inference results, and failure details through
  tenant-scoped API responses.

## API

- `POST /api/v1/workflows`
- `GET /api/v1/workflows?status=ACTIVE`
- `GET /api/v1/workflows/{workflow_id}`
- `PATCH /api/v1/workflows/{workflow_id}`
- `POST /api/v1/workflows/{workflow_id}/runs`
- `GET /api/v1/workflows/{workflow_id}/runs`
- `GET /api/v1/workflow-runs/{run_id}`
- `POST /api/v1/tasks/{task_id}/cancel` cancels a queued or running workflow
  run using its associated task.

Workflow definitions require `nexus.workflow.manage`; reading definitions and
runs requires `nexus.workflow.read`; queueing runs requires
`nexus.workflow.run`. Owner and operator roles receive these permissions;
viewers can read only. Every database lookup is scoped to the authenticated
tenant.

## Execution and reliability

Each workflow run creates a `ControlTask` and an `automation.workflow` work
item. The existing worker retries transient provider failures up to three
attempts with exponential backoff and applies emergency-stop checks before
inference. A successful step's result is persisted before the next step starts.
Processing remains at-least-once if a provider returns a result but the worker
fails before that step is committed.

Steps execute sequentially, but later steps receive the original run input;
previous step outputs are returned in the run result and are not automatically
passed as context to later steps. Configure an enabled chat model for the same
tenant. An optional provider on a step selects among that tenant's enabled
models.

## Explicit exclusions

- No recurring schedules, event triggers, arbitrary expressions, code
  execution, branching/parallel graphs, or output-to-input variable mapping.
- No tool execution, automatic agent delegation, or permission escalation.
- No vector retrieval or implicit knowledge-base injection.
- Workflow input, prompts, and inference results are stored unencrypted in the
  application database. Do not include secrets in them.

## Acceptance

- Workflow activation is required before a run can be queued.
- Tenant boundaries apply to workflows, runs, tasks, and worker model
  selection.
- Delayed work is not claimable until its `available_at` time.
- Conditions skip non-matching steps without invoking a provider.
- Worker retries do not repeat already committed steps.
- Cancellation synchronizes the associated task and workflow-run states.
- Audit events record workflow lifecycle and run outcomes without including
  prompts, input values, or inference content.
