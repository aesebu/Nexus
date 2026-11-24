from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import socket

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.integrations.webhooks import (
    WebhookConfigurationError,
    send_signed_webhook,
)
from app.models import (
    IntegrationWebhookDelivery,
    TaskStatus,
    TaskWorkItem,
    WorkItemStatus,
)
from app.schemas import IntegrationWebhookCreate, IntegrationWebhookUpdate
from app.worker import process_next_work_item
from tests.conftest import auth_headers


def _webhook_payload() -> dict:
    return {
        "name": "Ticket events",
        "target_url": "https://hooks.example.com/nexus/events",
        "secret_name": "webhook-signing",
        "event_types": ["ticket.created"],
    }


def _configure_webhook_environment(monkeypatch):
    monkeypatch.setattr(settings, "integration_allowed_hosts", "hooks.example.com")
    monkeypatch.setattr(
        settings,
        "secret_encryption_key",
        SecretStr(Fernet.generate_key().decode("ascii")),
    )


def _create_enabled_webhook(client, headers):
    secret = client.put(
        "/api/v1/secrets",
        headers=headers,
        json={"name": "webhook-signing", "value": "test-signing-key"},
    )
    assert secret.status_code == 200
    created = client.post(
        "/api/v1/integrations/webhooks",
        headers=headers,
        json=_webhook_payload(),
    )
    assert created.status_code == 201
    webhook = created.json()
    enabled = client.patch(
        f"/api/v1/integrations/webhooks/{webhook['id']}",
        headers=headers,
        json={"status": "ENABLED"},
    )
    assert enabled.status_code == 200
    return enabled.json()


def test_webhook_event_delivery_is_signed_and_retried(client, db_session, monkeypatch):
    _configure_webhook_environment(monkeypatch)
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    webhook = _create_enabled_webhook(client, owner_headers)
    event = client.post(
        "/api/v1/events",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={
            "event_type": "ticket.created",
            "payload": {"ticket_id": "T-42"},
        },
    )
    assert event.status_code == 201
    delivery = db_session.scalar(
        select(IntegrationWebhookDelivery).where(
            IntegrationWebhookDelivery.event_id == event.json()["id"]
        )
    )
    assert delivery is not None
    work_item = db_session.get(TaskWorkItem, delivery.task_id)
    assert work_item is not None
    assert work_item.work_type == "integration.webhook"
    assert work_item.payload == {"delivery_id": delivery.id}

    class FlakySender:
        def __init__(self):
            self.calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            return 503 if len(self.calls) == 1 else 204

    sender = FlakySender()
    first_attempt_at = datetime.now(timezone.utc)
    assert process_next_work_item(
        db_session,
        worker_id="webhook-worker",
        webhook_sender=sender,
        now=first_attempt_at,
    )
    assert work_item.status == WorkItemStatus.PENDING
    assert work_item.attempts == 1

    assert process_next_work_item(
        db_session,
        worker_id="webhook-worker",
        webhook_sender=sender,
        now=first_attempt_at + timedelta(seconds=10),
    )
    assert work_item.status == WorkItemStatus.COMPLETED
    assert len(sender.calls) == 2
    assert sender.calls[0]["signing_secret"] == "test-signing-key"
    assert b'"ticket_id":"T-42"' in sender.calls[0]["body"]

    deliveries = client.get(
        f"/api/v1/integrations/webhooks/{webhook['id']}/deliveries",
        headers=owner_headers,
    )
    assert deliveries.status_code == 200
    assert deliveries.json()[0]["status"] == TaskStatus.COMPLETED.value
    assert deliveries.json()[0]["attempts"] == 2


def test_webhook_registry_is_tenant_scoped_and_rejects_unsafe_destinations(
    client,
    monkeypatch,
):
    _configure_webhook_environment(monkeypatch)
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    assert client.put(
        "/api/v1/secrets",
        headers=owner_headers,
        json={"name": "webhook-signing", "value": "test-signing-key"},
    ).status_code == 200

    insecure = client.post(
        "/api/v1/integrations/webhooks",
        headers=owner_headers,
        json={**_webhook_payload(), "target_url": "http://hooks.example.com/events"},
    )
    assert insecure.status_code == 422
    unapproved = client.post(
        "/api/v1/integrations/webhooks",
        headers=owner_headers,
        json={
            **_webhook_payload(),
            "target_url": "https://other.example.com/events",
        },
    )
    assert unapproved.status_code == 422

    webhook = _create_enabled_webhook(client, owner_headers)
    other_tenant_headers = auth_headers(role="owner", tenant_id="tenant-b")
    assert client.get(
        f"/api/v1/integrations/webhooks/{webhook['id']}",
        headers=other_tenant_headers,
    ).status_code == 404
    assert client.get(
        f"/api/v1/integrations/webhooks/{webhook['id']}/deliveries",
        headers=other_tenant_headers,
    ).status_code == 404
    assert client.patch(
        f"/api/v1/integrations/webhooks/{webhook['id']}",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"status": "DISABLED"},
    ).status_code == 403
    secret_id = next(
        secret["id"]
        for secret in client.get("/api/v1/secrets", headers=owner_headers).json()
        if secret["name"] == "webhook-signing"
    )
    assert client.delete(
        f"/api/v1/secrets/{secret_id}",
        headers=owner_headers,
    ).status_code == 409

    monkeypatch.setattr(settings, "integration_allowed_hosts", "")
    disabled = client.patch(
        f"/api/v1/integrations/webhooks/{webhook['id']}",
        headers=owner_headers,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    assert client.delete(
        f"/api/v1/secrets/{secret_id}",
        headers=owner_headers,
    ).status_code == 204


def test_webhook_sender_signs_payload_and_blocks_private_dns(monkeypatch):
    monkeypatch.setattr(settings, "integration_allowed_hosts", "hooks.example.com")
    body = b'{"ok":true}'
    secret = "local-test-secret"

    class FakeResponse:
        status = 202

    class FakeConnection:
        def __init__(self, hostname, *, address, **_kwargs):
            assert hostname == "hooks.example.com"
            assert address == "93.184.216.34"
            self.request_args = None

        def request(self, method, path, *, body, headers):
            self.request_args = (method, path, body, headers)

        def getresponse(self):
            method, path, request_body, headers = self.request_args
            expected_signature = hmac.new(
                secret.encode("utf-8"),
                request_body,
                hashlib.sha256,
            ).hexdigest()
            assert method == "POST"
            assert path == "/nexus/events"
            assert request_body == body
            assert headers["X-Nexus-Signature"] == f"sha256={expected_signature}"
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(
        "app.integrations.webhooks.socket.getaddrinfo",
        lambda _hostname, port, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port),
            )
        ],
    )
    monkeypatch.setattr(
        "app.integrations.webhooks._PinnedHTTPSConnection",
        FakeConnection,
    )
    assert (
        send_signed_webhook(
            target_url="https://hooks.example.com/nexus/events",
            signing_secret=secret,
            body=body,
            event_id="event-1",
            delivery_id="delivery-1",
        )
        == 202
    )

    monkeypatch.setattr(
        "app.integrations.webhooks.socket.getaddrinfo",
        lambda _hostname, port, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1", port),
            )
        ],
    )
    with pytest.raises(WebhookConfigurationError):
        send_signed_webhook(
            target_url="https://hooks.example.com/nexus/events",
            signing_secret=secret,
            body=body,
            event_id="event-1",
            delivery_id="delivery-1",
        )


def test_webhook_schema_rejects_invalid_events_and_null_updates():
    with pytest.raises(ValidationError):
        IntegrationWebhookCreate.model_validate(
            {**_webhook_payload(), "event_types": ["ticket.created"] * 2}
        )
    with pytest.raises(ValidationError):
        IntegrationWebhookCreate.model_validate(
            {**_webhook_payload(), "event_types": ["*"]}
        )
    with pytest.raises(ValidationError):
        IntegrationWebhookUpdate.model_validate({"secret_name": None})
    with pytest.raises(ValidationError):
        IntegrationWebhookUpdate.model_validate({})
