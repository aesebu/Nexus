import pytest
from pydantic import ValidationError

from app.schemas import ApplicationRegistrationCreate, ApplicationRegistrationUpdate
from tests.conftest import auth_headers


def _application_payload(app_key: str = "case-dashboard") -> dict:
    return {
        "app_key": app_key,
        "name": "Case Dashboard",
        "description": "A tenant-owned application profile",
        "permission_scopes": ["nexus.task.read", "nexus.workflow.read"],
        "data_scopes": ["cases.read", "workflows.read"],
    }


def test_application_registry_lifecycle_and_tenant_isolation(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/applications",
        headers=owner_headers,
        json=_application_payload(),
    )
    assert created.status_code == 201
    application = created.json()
    assert application["status"] == "REGISTERED"
    assert application["app_key"] == "case-dashboard"

    duplicate = client.post(
        "/api/v1/applications",
        headers=owner_headers,
        json=_application_payload(),
    )
    assert duplicate.status_code == 409

    other_tenant_headers = auth_headers(role="owner", tenant_id="tenant-b")
    other_tenant = client.post(
        "/api/v1/applications",
        headers=other_tenant_headers,
        json=_application_payload(),
    )
    assert other_tenant.status_code == 201
    assert other_tenant.json()["id"] != application["id"]

    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    assert client.get(
        f"/api/v1/applications/{application['id']}",
        headers=operator_headers,
    ).status_code == 200
    assert client.patch(
        f"/api/v1/applications/{application['id']}",
        headers=operator_headers,
        json={"status": "DISABLED"},
    ).status_code == 403

    enabled = client.patch(
        f"/api/v1/applications/{application['id']}",
        headers=owner_headers,
        json={"status": "ENABLED", "data_scopes": ["cases.read"]},
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "ENABLED"
    assert enabled.json()["data_scopes"] == ["cases.read"]

    assert client.get(
        "/api/v1/applications",
        headers=owner_headers,
        params={"status": "ENABLED"},
    ).json()[0]["id"] == application["id"]
    assert client.get(
        f"/api/v1/applications/{application['id']}",
        headers=other_tenant_headers,
    ).status_code == 404

    audit = client.get("/api/v1/audit", headers=owner_headers).json()
    application_events = [
        event
        for event in audit
        if event["resource_id"] == application["id"]
    ]
    assert {event["action"] for event in application_events} == {
        "APPLICATION_REGISTERED",
        "APPLICATION_UPDATED",
    }
    assert all(
        "nexus.task.read" not in str(event["detail"])
        for event in application_events
    )


def test_application_registry_permissions_and_validation(client):
    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    assert client.post(
        "/api/v1/applications",
        headers=operator_headers,
        json=_application_payload(),
    ).status_code == 403

    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    assert client.get("/api/v1/applications", headers=viewer_headers).status_code == 200

    with pytest.raises(ValidationError):
        ApplicationRegistrationCreate.model_validate(
            {
                **_application_payload(),
                "permission_scopes": ["nexus.unrecognized.permission"],
            }
        )
    with pytest.raises(ValidationError):
        ApplicationRegistrationCreate.model_validate(
            {
                **_application_payload(),
                "data_scopes": ["bad scope"],
            }
        )
    with pytest.raises(ValidationError):
        ApplicationRegistrationUpdate.model_validate({"name": None})
    with pytest.raises(ValidationError):
        ApplicationRegistrationUpdate.model_validate({})
