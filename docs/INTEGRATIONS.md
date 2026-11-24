# Outbound Webhook Integrations

Phase 11 connects selected NEXUS events to external services using signed
outbound HTTPS webhooks.

## Configure deployment egress

Set `NEXUS_INTEGRATION_ALLOWED_HOSTS` to a comma-separated list of exact
external hostnames, such as `hooks.example.com`. Destinations are restricted
to HTTPS port 443; redirect following is disabled, DNS results must be public,
and connections are pinned to a resolved IP with TLS hostname verification.
Use deployment network controls as an additional egress boundary.

Set `NEXUS_SECRET_ENCRYPTION_KEY` and create the signing secret through
`PUT /api/v1/secrets`. The HTTP API returns secret metadata only.

## Register and enable

```json
{
  "name": "Ticket platform",
  "target_url": "https://hooks.example.com/nexus/events",
  "secret_name": "ticket-webhook-signing",
  "event_types": [
    "ticket.created",
    "ticket.updated"
  ]
}
```

Create with `POST /api/v1/integrations/webhooks`, then enable with
`PATCH /api/v1/integrations/webhooks/{webhook_id}` and
`{"status":"ENABLED"}`. Configure the signing secret in the same tenant before
creating the subscription. Only newly published events matching one of the
selected exact event types are queued.

When the matching event is published, NEXUS creates a durable delivery task.
Inspect task status and attempts at
`GET /api/v1/integrations/webhooks/{webhook_id}/deliveries`. Disable a
subscription to prevent queued work from making an outbound request. A
disabled subscription can be re-enabled after its destination and signing
secret are available.

## Receiver verification

NEXUS sends a compact JSON body with `event_id`, `event_type`, `occurred_at`,
and `payload`. It signs the exact UTF-8 bytes of that body:

```text
X-Nexus-Signature: sha256=<hex HMAC-SHA256>
X-Nexus-Event-ID: <event id>
X-Nexus-Delivery-ID: <delivery id>
```

Verify the HMAC using the shared signing secret and compare signatures in
constant time. Use the delivery ID as an idempotency key: NEXUS retries
timeouts and HTTP 408, 425, 429, and 5xx responses, so a receiver can see the
same delivery more than once. HTTP redirects and other non-2xx responses are
not followed and are treated as permanent failures.

Subscription management is owner-only; all roles can inspect subscriptions and
delivery status. The subscription response contains the destination URL and
secret name, not the secret value. Avoid credentials in URL paths; URL query
strings and embedded credentials are rejected. Event payloads are sent as
provided and stored unencrypted in the NEXUS event journal.

See the [Phase 11 specification](./PHASE_11_INTEGRATION.md) for all security
boundaries and acceptance criteria.
