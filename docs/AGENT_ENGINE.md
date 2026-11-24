# Agent Engine

The Agent Engine stores tenant-scoped agent configuration and supports
explicitly invoked runs using the existing AI model registry and inference
provider. Apply the database migration with `alembic upgrade head`.

## Lifecycle and permissions

Agents are created with status `REGISTERED` unless specified otherwise. Only
`ENABLED` agents can run. Use `PATCH /api/v1/agents/{agent_id}` to update the
instructions, descriptive capabilities, declared tools, preferred provider,
or lifecycle status.

| Permission | Available actions |
|---|---|
| `nexus.agent.read` | List and inspect agents |
| `nexus.agent.manage` | Create and update agent registry entries |
| `nexus.agent.run` | Invoke an enabled agent or requested orchestration |

The built-in owner/operator roles can manage and run agents; viewers can read
the registry. Agent `capabilities` are metadata and do not grant application
permissions.

## Invoke one agent

```http
POST /api/v1/agents/{agent_id}/run
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{"prompt":"Analyze the supplied proposal."}
```

An agent's instructions are passed as a system message. Its optional
`preferred_provider` filters the existing deterministic model route. Declared
tools are passed to the model, and returned tool calls are metadata only; the
API does not execute them.

## Orchestrate agents

```http
POST /api/v1/agents/orchestrate
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "agent_ids":["<research-agent-id>","<analysis-agent-id>"],
  "prompt":"Review this proposal."
}
```

Orchestration is explicit and ordered: it invokes at most five enabled agents,
each independently receiving the same prompt, and returns one result per
agent. It is not an autonomous chain and does not pass outputs between agents.

Every invocation retains the AI Engine's tenant isolation, model routing,
audit behavior, and emergency-stop enforcement.
