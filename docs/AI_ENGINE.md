# AI Engine: Inference and Model Registry

The current AI Engine MVP accepts chat messages, routes them to a registered
model, and calls an OpenAI-compatible chat-completions endpoint. Provider
credentials are read from environment settings; prompts are not persisted.

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
must be from the user. Conversation messages are request-scoped and are not
stored by NEXUS. Clients that need conversation continuity must send the
relevant prior messages again.

The assistant prompt sets identity and response expectations; it is not an
authorization boundary. The assistant does not have tools or direct access to
tenant data or live system state, and it cannot execute commands. API
permissions and governance policies remain enforced by the application.

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
