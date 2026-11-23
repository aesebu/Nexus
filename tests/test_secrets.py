from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.models import AuditEvent, TenantSecret
from app.secrets import (
    SecretNotFoundError,
    SecretStoreError,
    decrypt_secret,
    encrypt_secret,
    resolve_secret,
)
from tests.conftest import auth_headers


def test_secret_encryption_round_trip_and_rejects_wrong_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "secret_encryption_key", SecretStr(key))

    ciphertext = encrypt_secret("sensitive-value")
    assert ciphertext != "sensitive-value"
    assert decrypt_secret(ciphertext) == "sensitive-value"

    monkeypatch.setattr(
        settings,
        "secret_encryption_key",
        SecretStr(Fernet.generate_key().decode("ascii")),
    )
    try:
        decrypt_secret(ciphertext)
    except SecretStoreError:
        pass
    else:
        raise AssertionError("A secret encrypted with another key must not decrypt")


def test_tenant_secret_api_encrypts_values_and_returns_metadata_only(
    client, db_session, monkeypatch
):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "secret_encryption_key", SecretStr(key))
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    secret_value = "provider-credential-value"

    created = client.put(
        "/api/v1/secrets",
        headers=owner_headers,
        json={"name": "provider.api_key", "value": secret_value},
    )
    assert created.status_code == 200
    assert created.json()["name"] == "provider.api_key"
    assert secret_value not in created.text

    secret = db_session.scalar(
        select(TenantSecret).where(
            TenantSecret.tenant_id == "tenant-a",
            TenantSecret.name == "provider.api_key",
        )
    )
    assert secret is not None
    assert secret.ciphertext != secret_value
    assert resolve_secret(
        db_session, tenant_id="tenant-a", name="provider.api_key"
    ) == secret_value
    try:
        resolve_secret(db_session, tenant_id="tenant-b", name="provider.api_key")
    except SecretNotFoundError:
        pass
    else:
        raise AssertionError("Secrets must not resolve across tenant boundaries")

    replacement_value = "replacement-credential-value"
    updated = client.put(
        "/api/v1/secrets",
        headers=owner_headers,
        json={"name": "provider.api_key", "value": replacement_value},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == created.json()["id"]
    assert replacement_value not in updated.text
    assert resolve_secret(
        db_session, tenant_id="tenant-a", name="provider.api_key"
    ) == replacement_value

    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    listed = client.get("/api/v1/secrets", headers=operator_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "provider.api_key"
    assert secret_value not in listed.text

    denied_write = client.put(
        "/api/v1/secrets",
        headers=operator_headers,
        json={"name": "provider.api_key", "value": "replacement"},
    )
    assert denied_write.status_code == 403

    other_tenant = client.get(
        "/api/v1/secrets",
        headers=auth_headers(role="owner", tenant_id="tenant-b"),
    )
    assert other_tenant.status_code == 200
    assert other_tenant.json() == []

    audit_events = list(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == "tenant-a")
        )
    )
    secret_events = [event for event in audit_events if event.action.startswith("SECRET_")]
    assert secret_events
    assert {event.action for event in secret_events} == {
        "SECRET_CREATED",
        "SECRET_UPDATED",
    }
    assert all(
        secret_value not in str(event.detail)
        and replacement_value not in str(event.detail)
        for event in secret_events
    )

    deleted = client.delete(
        f"/api/v1/secrets/{created.json()['id']}",
        headers=owner_headers,
    )
    assert deleted.status_code == 204
    try:
        resolve_secret(db_session, tenant_id="tenant-a", name="provider.api_key")
    except SecretNotFoundError:
        pass
    else:
        raise AssertionError("Deleted secrets must no longer be resolvable")


def test_secret_write_fails_closed_without_encryption_key(client, monkeypatch):
    monkeypatch.setattr(settings, "secret_encryption_key", None)
    response = client.put(
        "/api/v1/secrets",
        headers=auth_headers(role="owner", tenant_id="tenant-a"),
        json={"name": "provider.api_key", "value": "sensitive-value"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Secret encryption is not configured"
