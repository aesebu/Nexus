# Phase 05 - AI Engine

| Field | Value |
|---|---|
| Phase | 05 |
| Name | AI Engine |
| Deliverable | Persistent context, structured output, and tool-call declarations |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-05 |
| Version | 1.0 |

## Specification

Phase 05 completes the inference MVP with optional durable conversation
context, response-format negotiation, and tool-call metadata. It preserves the
existing model registry, deterministic routing, emergency-stop enforcement,
tenant isolation, and audit behavior.

## Components

| Component | Implementation | Purpose |
|---|---|---|
| Conversation registry | `AIConversation` | Tenant and actor scoped context container |
| Conversation history | `AIConversationMessage` | Ordered durable message history |
| Inference | `POST /api/v1/ai/infer` | Model inference with optional context |
| Conversation API | `/api/v1/ai/conversations` | Create, read, and delete context |
| Structured output | `response_format` | Return JSON parsed content |
| Tool declarations | `tools` | Expose provider tool definitions and call metadata |

## Boundaries

- Conversation history is private to one tenant and the actor who created it.
- Context loading is capped at 100 most recent stored messages.
- Tool calls are declarations/results only; NEXUS does not execute tools.
- Tool execution remains subject to separate application authorization and
  command governance.
- Audit events exclude prompts, responses, and conversation content.

## Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| AE-01 | Provider requests support structured response formats | Provider tests |
| AE-02 | Provider requests support tool declarations | Provider tests |
| AE-03 | Provider tool calls are returned without execution | API/provider tests |
| AE-04 | Conversation history is tenant and actor scoped | API tests |
| AE-05 | Context is persisted and reused across inference requests | API tests |
| AE-06 | Emergency stop and model routing remain enforced | Existing API tests |
