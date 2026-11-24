# Phase 06 - Agent Engine

| Field | Value |
|---|---|
| Phase | 06 |
| Name | Agent Intelligence / Agent Engine |
| Deliverable | Tenant-scoped agent registry, lifecycle, invocation, and orchestration |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-06 |
| Version | 1.0 |

## Specification

Phase 06 provides a managed registry of AI agent configurations and explicitly
invoked agent runs. Agents use the existing tenant-scoped model router and
inference provider, with the agent's instructions and declared tool schemas
passed as model context.

## Components

| Component | Implementation | Purpose |
|---|---|---|
| Agent registry | `AIAgent` | Tenant-owned identity, role, instructions, and declarations |
| Lifecycle | `REGISTERED`, `ENABLED`, `DISABLED` | Explicit activation before an agent can run |
| Agent invocation | `POST /api/v1/agents/{agent_id}/run` | Invoke one enabled agent on a user-supplied prompt |
| Orchestration | `POST /api/v1/agents/orchestrate` | Run up to five enabled agents on the same prompt |
| Authorization | `nexus.agent.*` permissions | Separate registry management, reading, and invocation |
| Audit | `AuditEvent` | Record agent changes/runs without storing prompt content |

## API

Create an agent (registered but not enabled by default):

```http
POST /api/v1/agents
Content-Type: application/json

{
  "name": "researcher",
  "agent_type": "research",
  "instructions": "Analyze the supplied request and report evidence.",
  "capabilities": ["research"],
  "tools": [],
  "status": "REGISTERED"
}
```

Enable the agent using `PATCH /api/v1/agents/{agent_id}`, then invoke it with
`POST /api/v1/agents/{agent_id}/run`. Run requests can include a Phase 05
conversation ID and response format. An orchestration request supplies an
ordered list of up to five enabled `agent_ids`; each agent receives the same
prompt and results are returned per agent.

## Security boundaries

- Registry objects and reads are tenant-scoped.
- Only `nexus.agent.manage` can create or change agents; `nexus.agent.run` is
  required to invoke agents.
- `REGISTERED` and `DISABLED` agents cannot be invoked.
- `capabilities` are descriptive metadata, not permission grants.
- Tool schemas are declarations only. Agent runs return tool-call metadata and
  never execute tools or grant agent permissions.
- Agent invocation uses existing inference routing and emergency-stop checks.
- Audit details contain agent/model metadata, not instructions, prompts, or
  generated content.

## Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| AG-01 | Agent creation and reads are tenant-scoped | API tests |
| AG-02 | Agents require explicit enablement to run | API tests |
| AG-03 | Agent instructions/tools reach the inference provider | API tests |
| AG-04 | Orchestration invokes only the requested enabled agents in order | API tests |
| AG-05 | Agent management, run, and read permissions are distinct | Permission/API tests |
| AG-06 | Agent actions produce audit evidence without prompt content | API tests |

## Out of scope

Autonomous scheduling, tool execution, agent-to-agent messaging, delegated
permission grants, parallel fan-out, and long-running agent-run queues are not
part of this MVP.
