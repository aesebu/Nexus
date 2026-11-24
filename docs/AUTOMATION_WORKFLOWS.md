# Automation Workflows

Automation workflows are tenant-scoped ordered sequences of AI inference steps
executed by the background worker.

## Create and activate

Create a draft workflow:

```json
{
  "name": "Review request",
  "description": "Summarize and review an incoming request",
  "steps": [
    {
      "id": "summarize",
      "prompt": "Summarize the request"
    },
    {
      "id": "review",
      "prompt": "Review the request for approval",
      "condition": {
        "path": "review_required",
        "equals": true
      },
      "response_format": {
        "type": "json_object"
      }
    }
  ]
}
```

Send the payload to `POST /api/v1/workflows`, then activate it with
`PATCH /api/v1/workflows/{workflow_id}` and `{"status":"ACTIVE"}`. Updates to
the step list increment the workflow version. Runs retain a snapshot of the
version and steps that were active when they were queued.

Each workflow has 1–10 steps with unique lowercase IDs. Prompts are limited to
10,000 characters, system prompts to 4,000 characters, and condition comparison
values to 4 KiB. Conditions support dotted object paths and equality only.

## Queue a run

```json
{
  "input": {
    "request_id": "REQ-1024",
    "review_required": true
  },
  "delay_seconds": 0
}
```

Send to `POST /api/v1/workflows/{workflow_id}/runs`. Input is limited to 16 KiB
of JSON, and `delay_seconds` can be set from 0 to 2,592,000 (30 days). The API
returns a queued run and its `task_id`. Use `GET /api/v1/workflow-runs/{run_id}`
or `GET /api/v1/workflows/{workflow_id}/runs` to inspect progress and results.
Cancel through `POST /api/v1/tasks/{task_id}/cancel`.

An enabled chat model must be registered for the tenant. A step may optionally
select a provider; otherwise the worker uses its normal model-priority ordering.
Each step receives its prompt, optional system prompt, and the original workflow
input as JSON. Previous outputs are included in the final ordered result, not
passed automatically to later steps.

The worker persists step results and resumes at unfinished steps after a
transient provider failure. Provider calls are at-least-once if a worker fails
after receiving a response but before committing that step. Run state is
terminal after success, permanent failure, retry exhaustion, or cancellation.

Workflow and run permissions are `nexus.workflow.read`,
`nexus.workflow.manage`, and `nexus.workflow.run`. Operators and owners can
manage and run workflows; viewers are read-only. Workflow records, inputs, and
results are tenant-scoped but stored unencrypted. Do not place secrets in
workflow prompts or run input. Workflow definitions cannot execute tools,
arbitrary code, or recurring/event-triggered jobs.

See [Phase 09 specification](./PHASE_09_AUTOMATION_WORKFLOWS.md) for detailed
scope and acceptance criteria.
