# Phase 11 — Integrated Platform

## Goal

Connect the tenant event journal to external systems through controlled,
signed outbound webhooks, using the existing durable worker queue and encrypted
tenant secret store.

## MVP scope

- Owners register, read, and update tenant-scoped webhook subscriptions.
- A subscription selects exact event types and references a signing secret by
  name in the tenant secret store. Secret values never appear in subscription
  responses or work-item payloads.
- Only explicitly enabled subscriptions receive newly published matching
  events. Event publication and delivery-task creation share one database
  transaction.
- Deliveries run through `TaskWorkItem` with the existing lease and bounded
  retry behavior. Each delivery has an inspectable task state and attempt
  count.
- Requests are HTTPS POSTs signed with HMAC-SHA256 in
  `X-Nexus-Signature: sha256=<hex>`. The event and delivery IDs are included in
  request headers for receiver-side deduplication.

## Destination safety

The deployment must configure `NEXUS_INTEGRATION_ALLOWED_HOSTS` as a
comma-separated list of exact hostnames, for example:

```text
NEXUS_INTEGRATION_ALLOWED_HOSTS=hooks.example.com,events.partner.example
```

Destinations must use HTTPS on port 443, have an allowlisted hostname, and
must not include URL credentials, a query string, or a fragment. At delivery
time NEXUS resolves the hostname, rejects non-public addresses, pins the
connection to a verified public address, verifies TLS certificates and host
identity, and does not follow redirects. Deployments should additionally
enforce outbound network policy.

The destination path is stored and returned to authorized tenant readers; do
not place credentials or tokens in that path. Use the encrypted secret store
for signing keys. Deleting a secret referenced by an enabled subscription is
rejected; disable the subscription first.

## API and permissions

- `POST /api/v1/integrations/webhooks`
- `GET /api/v1/integrations/webhooks?status=ENABLED`
- `GET /api/v1/integrations/webhooks/{webhook_id}`
- `PATCH /api/v1/integrations/webhooks/{webhook_id}`
- `GET /api/v1/integrations/webhooks/{webhook_id}/deliveries`
- `POST /api/v1/events` publishes to the journal and queues matching deliveries

`nexus.integration.manage` is owner-only. Owner, operator, and viewer roles
have `nexus.integration.read`; existing event-publish permission remains
unchanged. A tenant may register at most 100 subscriptions, and each
subscription may select 1–64 unique event types.

## Delivery semantics

- HTTP 2xx completes a delivery.
- HTTP 408, 425, 429, and 5xx responses and transport/DNS failures are retried.
- Other non-2xx responses, including redirects, fail permanently.
- Retries use the worker's existing maximum of three attempts and exponential
  backoff. Delivery is at-least-once; receivers should deduplicate by
  `X-Nexus-Delivery-ID`.
- Disabling a subscription prevents pending deliveries from sending; those
  tasks fail closed when claimed.
- Audit events record subscription changes, queued deliveries, and terminal
  outcomes without logging secrets, event payloads, response bodies, or full
  destination URLs.

## Explicit exclusions

- No inbound webhooks, broker, event replay, scheduled sync, or generic
  arbitrary-URL HTTP client.
- No dynamic headers, redirect following, non-HTTPS targets, custom ports, or
  embedded URL credentials.
- No guarantee of exactly-once delivery; receivers must be idempotent.
- Webhook payloads contain the event payload and are not encrypted at rest.
