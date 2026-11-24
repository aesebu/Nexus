# Phase 13 — Continuous Improvement

## Goal

Capture bounded human feedback on persisted AI responses and expose
tenant-scoped aggregate quality signals for review.

## MVP scope

- Persist model attribution on newly generated assistant conversation messages.
- Allow the conversation creator to submit or update a 1–5 rating for an
  assistant message in their own tenant conversation.
- Store one current rating per actor and response; do not collect free-text
  feedback or duplicate the response content.
- Expose rating counts and average ratings grouped by model to tenant owners.
- Record feedback changes in the audit log without including conversation
  content.
- Keep all feedback and summaries tenant-scoped.

## API

- `PUT /api/v1/ai/messages/{message_id}/feedback` creates or updates the
  caller's rating.
- `GET /api/v1/ai/evaluations/summary` returns aggregate feedback by model and
  is owner-only.

The feedback write endpoint requires `nexus.ai.infer` and the caller must own
the conversation containing the assistant response. Cross-tenant, non-owner,
and non-assistant message lookups return not found. The summary requires
`nexus.ai.evaluation.read`.

## Acceptance criteria

- Only assistant responses from the caller's own tenant conversation can be
  rated.
- A caller has at most one current rating per response; subsequent PUTs update
  the value instead of creating duplicates.
- Ratings outside 1–5 are rejected.
- Summary results contain counts and averages only, are tenant-scoped, and
  never return prompts, responses, or feedback text.
- Older conversation responses without model attribution remain rateable and
  appear in an unassigned-model aggregate.
- Schema upgrade and downgrade work on SQLite and PostgreSQL-compatible
  migrations.

## Explicit exclusions

- No free-text comments, response replay, model training, automated evaluation,
  automatic model routing changes, or provider-specific analytics.
- Feedback is a human review signal, not proof of factual correctness or a
  safety certification.
- Aggregate ratings do not replace incident handling, model evaluation
  datasets, or privacy and retention policies.

## Status

Complete (MVP). The feedback API and tenant/model aggregates are covered by
focused API tests and the full test suite.
