from tests.conftest import auth_headers


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_command_lifecycle_and_audit(client):
    headers = auth_headers()

    created = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "research", "payload": {"topic": "NEXUS"}},
    )
    assert created.status_code == 201
    command = created.json()
    assert command["status"] == "RECEIVED"

    approved = client.post(
        f"/api/v1/commands/{command['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    executed = client.post(
        f"/api/v1/commands/{command['id']}/execute",
        headers=headers,
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "COMPLETED"
    assert executed.json()["result"] == "Executed successfully"

    audit = client.get("/api/v1/audit", headers=headers)
    assert audit.status_code == 200
    actions = {event["action"] for event in audit.json()}
    assert {"COMMAND_CREATED", "COMMAND_APPROVED", "COMMAND_EXECUTED"} <= actions


def test_emergency_stop_blocks_new_commands(client):
    owner_headers = auth_headers(role="owner")

    stop = client.post("/api/v1/emergency-stop", headers=owner_headers)
    assert stop.status_code == 200
    assert stop.json()["active"] is True

    blocked = client.post(
        "/api/v1/commands",
        headers=owner_headers,
        json={"type": "research", "payload": {}},
    )
    assert blocked.status_code == 409

    cleared = client.delete("/api/v1/emergency-stop", headers=owner_headers)
    assert cleared.status_code == 200
    assert cleared.json()["active"] is False


def test_tenant_isolation(client):
    tenant_a = auth_headers(tenant_id="tenant-a")
    tenant_b = auth_headers(tenant_id="tenant-b")

    created = client.post(
        "/api/v1/commands",
        headers=tenant_a,
        json={"type": "secret", "payload": {}},
    )
    command_id = created.json()["id"]

    denied = client.get(
        f"/api/v1/commands/{command_id}",
        headers=tenant_b,
    )
    assert denied.status_code == 404
