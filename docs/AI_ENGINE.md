# AI Engine: Inference and Model Registry

The AI Engine accepts chat messages, routes them to a registered model, and
calls an OpenAI-compatible chat-completions endpoint. It supports optional
tenant/actor-scoped conversation persistence, JSON structured output, and
provider tool-call declarations. Provider credentials are read from environment
settings.

## Configure the provider

Set these variables before starting the API:

```env
NEXUS_AI_BASE_URL=https://api.openai.com/v1
NEXUS_AI_API_KEY=your-provider-key
```

For a compatible local or hosted service, set `NEXUS_AI_BASE_URL` to its `/v1`
API root. Do not commit provider keys. Only the `openai-compatible` provider is
implemented; other registered provider names return `501` for inference.

## Register and route a model

Register a model with provider `openai-compatible` and the `chat` capability:

```http
POST /api/v1/models
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "name": "chat-primary",
  "provider": "openai-compatible",
  "model_identifier": "<provider-model-id>",
  "capabilities": ["chat"],
  "status": "ENABLED",
  "priority": 100
}
```

Models are selected within the authenticated tenant by enabled status, `chat`
capability, and descending priority, with name as a deterministic tie-breaker.
The optional `provider` field on an inference request filters candidates.

To list registered models, call `GET /api/v1/models`. Update a model with
`PATCH /api/v1/models/{model_id}`. Model names are unique within a tenant at
the API level.

## Run inference

```http
POST /api/v1/ai/infer
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "messages": [
    {"role": "system", "content": "Answer clearly and concisely."},
    {"role": "user", "content": "What is NEXUS?"}
  ],
  "temperature": 0.2,
  "max_tokens": 256
}
```

Messages are request-scoped and support `system`, `user`, and `assistant`
roles. `temperature` is limited to 0–2 and `max_tokens` to 1–8192. The response
includes the selected model, generated content, and token counts when supplied
by the provider.

Inference requires `nexus.ai.infer` permission and is blocked while the tenant's
emergency stop is active. Successful audit events record the model/provider
and usage counts but never prompt or response content.

## NEXUS assistant

Use `POST /api/v1/nexus/chat` for the NEXUS-branded assistant. It uses the
same tenant model routing, provider configuration, authorization, emergency
stop, and audit behavior as `/api/v1/ai/infer`, and prepends a fixed NEXUS
identity prompt. Supply only `user` and `assistant` messages; the final message
must be from the user. By default, conversation messages are request-scoped.
For durable context, create a conversation and pass its `conversation_id`.

The assistant prompt sets identity and response expectations; it is not an
authorization boundary. The assistant has no built-in access to tenant data or live system
state. Optional tool schemas can be passed, but tool calls are returned as
metadata only and are never executed by the assistant endpoint. API permissions
and governance policies remain enforced by the application.

## Persistent conversations

Create a tenant/actor-scoped conversation before inference:

```http
POST /api/v1/ai/conversations
Content-Type: application/json

{"title":"Planning"}
```

Pass the returned `conversation_id` on `/ai/infer` requests. NEXUS adds prior
stored messages to the provider context, persists the submitted user/assistant
messages and the assistant response, and limits context loading to 100 stored
messages. Conversations cannot be read or deleted by another actor or tenant.
Use `GET /api/v1/ai/conversations/{conversation_id}/messages` to inspect history
and `DELETE /api/v1/ai/conversations/{conversation_id}` to remove it.

Prompts and responses are stored in conversation history. This is user data:
operators must apply database access controls and retention procedures.

## Human response feedback

When inference uses a persistent conversation, the response includes
`response_message_id`. The conversation creator can submit or update a rating
for that assistant response:

```http
PUT /api/v1/ai/messages/{response_message_id}/feedback
Content-Type: application/json

{"rating": 4}
```

Ratings are integers from 1 to 5. Each actor has one current rating per
response. No free-text feedback is collected. Only tenant owners can read
`GET /api/v1/ai/evaluations/summary`, which reports rating count and average
grouped by model; it does not return prompts or responses. Older conversation
messages without model attribution are included in an unassigned group.
Feedback is for human review and does not train models or change routing.

## Structured output and tools

An inference request may include `response_format` for JSON output:

```json
{
  "messages":[{"role":"user","content":"Return a JSON status"}],
  "response_format":{"type":"json_object"}
}
```

For a named JSON Schema, use:

```json
{
  "type":"json_schema",
  "json_schema":{"name":"status","schema":{"type":"object"}}
}
```

Tool declarations may be supplied with `tools`. Provider-declared tool calls
are returned in `tool_calls`; NEXUS does not execute tools automatically.
Execution, authorization, and audit of any tool call must happen in a separate
application/governance workflow.

## Development seed data

The optional seed command inserts disabled placeholder models for the selected
tenant. It is idempotent and skips existing tenant/model-name pairs. It does
not enable models, create credentials, or run automatically:

```bash
python -m app.seed_models --tenant-id demo
```

The command uses the database configured by `NEXUS_DATABASE_URL`; use a
development database. Replace placeholder model identifiers and explicitly
enable a model before using inference.

## Roles and project defaults

The current authorization roles are defined in [`app/security.py`](../app/security.py):

| Role | Model registry | Inference |
|---|---|---|
| `owner` | Create, read, update, and route | Allowed |
| `operator` | Create, read, update, and route | Allowed |
| `viewer` | Read only | Not allowed |

There is no user or role database table in the MVP. Requests use a JWT containing
`sub`, `role`, and `tenant_id`; `X-Tenant-ID` must match the token tenant. The
JWT issuer is outside this API.
