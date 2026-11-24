from datetime import datetime, timedelta, timezone
import httpx

from tests.conftest import auth_headers
from app.ai.providers import (
    InferenceResult,
    OpenAICompatibleProvider,
    ProviderTimeoutError,
)
from app.api.routes import get_inference_provider
from app.core.config import Settings
from app.main import app
from app.models import CommandPolicyVersion, TaskWorkItem
from app.worker import process_next_work_item


class StubInferenceProvider:
    provider_name = "openai-compatible"

    def generate(self, **kwargs):
        self.request = kwargs
        return InferenceResult(
            content="Hello from the model",
            input_tokens=8,
            output_tokens=4,
        )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_liveness_and_readiness(client):
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json() == {"status": "alive"}

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


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
        headers=auth_headers(subject="approver-user"),
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


def test_viewer_can_read_command_but_not_cancel_it(client):
    operator_headers = auth_headers(role="operator")
    created = client.post(
        "/api/v1/commands",
        headers=operator_headers,
        json={"type": "research", "payload": {}},
    )
    command_id = created.json()["id"]

    viewed = client.get(
        f"/api/v1/commands/{command_id}",
        headers=auth_headers(role="viewer"),
    )
    assert viewed.status_code == 200

    denied = client.post(
        f"/api/v1/commands/{command_id}/cancel",
        headers=auth_headers(role="viewer"),
    )
    assert denied.status_code == 403


def test_cancel_command_lifecycle(client):
    headers = auth_headers(role="operator")
    created = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "research", "payload": {}, "require_approval": False},
    )
    command_id = created.json()["id"]

    cancelled = client.post(
        f"/api/v1/commands/{command_id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    denied = client.post(
        f"/api/v1/commands/{command_id}/approve",
        headers=headers,
    )
    assert denied.status_code == 409


def test_list_commands_is_tenant_scoped_and_filterable(client):
    tenant_a_headers = auth_headers(role="viewer", tenant_id="tenant-a")

    policy = client.post(
        "/api/v1/policies/commands",
        headers=auth_headers(role="owner", tenant_id="tenant-a"),
        json={"command_type": "approved", "require_approval": False},
    )
    assert policy.status_code == 201

    received = client.post(
        "/api/v1/commands",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"type": "received", "payload": {}},
    )
    assert received.status_code == 201

    approved = client.post(
        "/api/v1/commands",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"type": "approved", "payload": {}, "require_approval": False},
    )
    assert approved.status_code == 201

    client.post(
        "/api/v1/commands",
        headers=auth_headers(role="operator", tenant_id="tenant-b"),
        json={"type": "other-tenant", "payload": {}},
    )

    tenant_a_commands = client.get(
        "/api/v1/commands",
        headers=tenant_a_headers,
    )
    assert tenant_a_commands.status_code == 200
    assert {command["type"] for command in tenant_a_commands.json()} == {"received", "approved"}

    approved_commands = client.get(
        "/api/v1/commands?status=APPROVED",
        headers=tenant_a_headers,
    )
    assert approved_commands.status_code == 200
    assert len(approved_commands.json()) == 1
    assert approved_commands.json()[0]["type"] == "approved"


def test_unconfigured_command_fails_closed_and_requires_separate_approver(client):
    creator_headers = auth_headers(role="operator", subject="creator")
    created = client.post(
        "/api/v1/commands",
        headers=creator_headers,
        json={
            "type": "unconfigured",
            "payload": {},
            "require_approval": False,
        },
    )
    assert created.status_code == 201
    command = created.json()
    assert command["status"] == "RECEIVED"

    self_approval = client.post(
        f"/api/v1/commands/{command['id']}/approve",
        headers=creator_headers,
    )
    assert self_approval.status_code == 409

    approved = client.post(
        f"/api/v1/commands/{command['id']}/approve",
        headers=auth_headers(role="operator", subject="different-operator"),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


def test_command_policy_forces_approval_and_is_tenant_scoped(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    policy = client.post(
        "/api/v1/policies/commands",
        headers=owner_headers,
        json={
            "command_type": "sensitive",
            "require_approval": True,
            "require_different_approver": True,
            "description": "Sensitive operations require human approval.",
        },
    )
    assert policy.status_code == 201
    policy_id = policy.json()["id"]

    duplicate = client.post(
        "/api/v1/policies/commands",
        headers=owner_headers,
        json={"command_type": "sensitive"},
    )
    assert duplicate.status_code == 409

    created = client.post(
        "/api/v1/commands",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"type": "sensitive", "payload": {}, "require_approval": False},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "RECEIVED"

    other_tenant_policy = client.get(
        "/api/v1/policies/commands",
        headers=auth_headers(role="owner", tenant_id="tenant-b"),
    )
    assert other_tenant_policy.status_code == 200
    assert other_tenant_policy.json() == []

    cross_tenant_update = client.patch(
        f"/api/v1/policies/commands/{policy_id}",
        headers=auth_headers(role="owner", tenant_id="tenant-b"),
        json={"enabled": False},
    )
    assert cross_tenant_update.status_code == 404


def test_only_owner_can_manage_command_policies(client):
    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/policies/commands",
        headers=operator_headers,
        json={"command_type": "routine", "require_approval": False},
    )
    assert created.status_code == 403

    viewer_read = client.get(
        "/api/v1/policies/commands",
        headers=auth_headers(role="viewer", tenant_id="tenant-a"),
    )
    assert viewer_read.status_code == 403


def test_command_policy_versions_are_immutable_tenant_scoped_and_audited(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/policies/commands",
        headers=owner_headers,
        json={"command_type": "versioned", "require_approval": True},
    )
    assert created.status_code == 201
    policy = created.json()
    assert policy["version"] == 1

    updated = client.patch(
        f"/api/v1/policies/commands/{policy['id']}",
        headers=owner_headers,
        json={"require_approval": False},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    no_op = client.patch(
        f"/api/v1/policies/commands/{policy['id']}",
        headers=owner_headers,
        json={"require_approval": False},
    )
    assert no_op.status_code == 200
    assert no_op.json()["version"] == 2

    versions = client.get(
        f"/api/v1/policies/commands/{policy['id']}/versions",
        headers=owner_headers,
    )
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [1, 2]
    assert versions.json()[0]["snapshot"]["require_approval"] is True
    assert versions.json()[1]["snapshot"]["require_approval"] is False
    assert versions.json()[1]["changed_by"] == "test-user"

    command = client.post(
        "/api/v1/commands",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"type": "versioned", "payload": {}, "require_approval": False},
    )
    assert command.status_code == 201
    assert command.json()["status"] == "APPROVED"

    audit = client.get(
        "/api/v1/audit",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
    )
    creation_event = next(
        event
        for event in audit.json()
        if event["resource_id"] == command.json()["id"]
        and event["action"] == "COMMAND_CREATED"
    )
    assert creation_event["detail"]["policy_version"] == 2
    assert creation_event["detail"]["policy_snapshot"]["require_approval"] is False

    cross_tenant = client.get(
        f"/api/v1/policies/commands/{policy['id']}/versions",
        headers=auth_headers(role="owner", tenant_id="tenant-b"),
    )
    assert cross_tenant.status_code == 404


def test_legacy_policy_gets_baseline_version_before_update(client, db_session):
    headers = auth_headers(role="owner", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/policies/commands",
        headers=headers,
        json={"command_type": "legacy", "require_approval": True},
    )
    policy_id = created.json()["id"]

    db_session.query(CommandPolicyVersion).delete()
    db_session.commit()

    legacy_history = client.get(
        f"/api/v1/policies/commands/{policy_id}/versions",
        headers=headers,
    )
    assert legacy_history.status_code == 200
    assert [item["version"] for item in legacy_history.json()] == [1]
    assert legacy_history.json()[0]["snapshot"]["require_approval"] is True

    updated = client.patch(
        f"/api/v1/policies/commands/{policy_id}",
        headers=headers,
        json={"require_approval": False},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    history = client.get(
        f"/api/v1/policies/commands/{policy_id}/versions",
        headers=headers,
    )
    assert [item["version"] for item in history.json()] == [1, 2]
    assert history.json()[0]["snapshot"]["require_approval"] is True
    assert history.json()[1]["snapshot"]["require_approval"] is False


def test_disabled_auto_approval_policy_fails_closed(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    policy = client.post(
        "/api/v1/policies/commands",
        headers=owner_headers,
        json={"command_type": "routine", "require_approval": False},
    )
    assert policy.status_code == 201

    disabled = client.patch(
        f"/api/v1/policies/commands/{policy.json()['id']}",
        headers=owner_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    invalid_update = client.patch(
        f"/api/v1/policies/commands/{policy.json()['id']}",
        headers=owner_headers,
        json={"enabled": None},
    )
    assert invalid_update.status_code == 422

    created = client.post(
        "/api/v1/commands",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"type": "routine", "payload": {}, "require_approval": False},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "RECEIVED"


def test_payload_policy_requires_approval_when_nested_key_is_present(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    policy = client.post(
        "/api/v1/policies/commands",
        headers=owner_headers,
        json={
            "command_type": "transfer",
            "require_approval": False,
            "approval_payload_keys": ["destination.account"],
        },
    )
    assert policy.status_code == 201
    assert policy.json()["approval_payload_keys"] == ["destination.account"]

    creator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    matched = client.post(
        "/api/v1/commands",
        headers=creator_headers,
        json={
            "type": "transfer",
            "payload": {"destination": {"account": "account-123"}},
            "require_approval": False,
        },
    )
    assert matched.status_code == 201
    assert matched.json()["status"] == "RECEIVED"

    unmatched = client.post(
        "/api/v1/commands",
        headers=creator_headers,
        json={
            "type": "transfer",
            "payload": {"destination": {}},
            "require_approval": False,
        },
    )
    assert unmatched.status_code == 201
    assert unmatched.json()["status"] == "APPROVED"

    audit = client.get("/api/v1/audit", headers=creator_headers)
    command_audit = next(
        event
        for event in audit.json()
        if event["resource_id"] == matched.json()["id"]
        and event["action"] == "COMMAND_CREATED"
    )
    assert command_audit["detail"]["approval_payload_rule_matched"] is True
    assert "account-123" not in str(command_audit["detail"])

    updated = client.patch(
        f"/api/v1/policies/commands/{policy.json()['id']}",
        headers=owner_headers,
        json={"approval_payload_keys": ["destination.routing_number"]},
    )
    assert updated.status_code == 200
    assert updated.json()["approval_payload_keys"] == ["destination.routing_number"]

    old_rule_only = client.post(
        "/api/v1/commands",
        headers=creator_headers,
        json={
            "type": "transfer",
            "payload": {"destination": {"account": "account-456"}},
            "require_approval": False,
        },
    )
    assert old_rule_only.status_code == 201
    assert old_rule_only.json()["status"] == "APPROVED"

    updated_rule_match = client.post(
        "/api/v1/commands",
        headers=creator_headers,
        json={
            "type": "transfer",
            "payload": {"destination": {"routing_number": "route-789"}},
            "require_approval": False,
        },
    )
    assert updated_rule_match.status_code == 201
    assert updated_rule_match.json()["status"] == "RECEIVED"

    cleared = client.patch(
        f"/api/v1/policies/commands/{policy.json()['id']}",
        headers=owner_headers,
        json={"approval_payload_keys": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["approval_payload_keys"] == []


def test_payload_policy_rejects_duplicate_and_invalid_paths(client):
    headers = auth_headers(role="owner", tenant_id="tenant-a")
    duplicate = client.post(
        "/api/v1/policies/commands",
        headers=headers,
        json={
            "command_type": "duplicate-path",
            "approval_payload_keys": ["destination.account", "destination.account"],
        },
    )
    assert duplicate.status_code == 422

    invalid = client.post(
        "/api/v1/policies/commands",
        headers=headers,
        json={
            "command_type": "invalid-path",
            "approval_payload_keys": ["destination..account"],
        },
    )
    assert invalid.status_code == 422


def test_system_registry_is_tenant_scoped_and_owner_managed(client):
    owner_a = auth_headers(role="owner", tenant_id="tenant-a")
    owner_b = auth_headers(role="owner", tenant_id="tenant-b")
    registration = {
        "name": "research-system",
        "system_type": "agent-platform",
        "version": "1.0",
        "capabilities": ["research", "summarize"],
        "description": "Development system registration",
    }

    created = client.post("/api/v1/systems", headers=owner_a, json=registration)
    assert created.status_code == 201
    system_id = created.json()["id"]
    assert created.json()["status"] == "REGISTERED"

    duplicate = client.post("/api/v1/systems", headers=owner_a, json=registration)
    assert duplicate.status_code == 409

    same_name_other_tenant = client.post(
        "/api/v1/systems",
        headers=owner_b,
        json=registration,
    )
    assert same_name_other_tenant.status_code == 201

    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    listed = client.get("/api/v1/systems", headers=viewer_headers)
    assert listed.status_code == 200
    assert [system["name"] for system in listed.json()] == ["research-system"]

    denied_update = client.patch(
        f"/api/v1/systems/{system_id}",
        headers=viewer_headers,
        json={"status": "ENABLED"},
    )
    assert denied_update.status_code == 403

    enabled = client.patch(
        f"/api/v1/systems/{system_id}",
        headers=owner_a,
        json={"status": "ENABLED"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "ENABLED"

    cross_tenant = client.get(
        f"/api/v1/systems/{system_id}",
        headers=owner_b,
    )
    assert cross_tenant.status_code == 404

    audit = client.get("/api/v1/audit", headers=owner_a)
    assert "SYSTEM_REGISTERED" in {event["action"] for event in audit.json()}
    assert "SYSTEM_UPDATED" in {event["action"] for event in audit.json()}


def test_system_registry_rejects_operator_write_and_null_capabilities(client):
    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    denied = client.post(
        "/api/v1/systems",
        headers=operator_headers,
        json={"name": "forbidden", "system_type": "agent"},
    )
    assert denied.status_code == 403

    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/systems",
        headers=owner_headers,
        json={"name": "valid", "system_type": "agent"},
    )
    assert created.status_code == 201

    invalid_update = client.patch(
        f"/api/v1/systems/{created.json()['id']}",
        headers=owner_headers,
        json={"capabilities": None},
    )
    assert invalid_update.status_code == 422


def test_task_lifecycle_and_audit(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Review model output", "description": "Manual QA"},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "PENDING"

    started = client.post(f"/api/v1/tasks/{task['id']}/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"
    assert started.json()["started_at"] is not None

    completed = client.post(
        f"/api/v1/tasks/{task['id']}/complete",
        headers=headers,
        json={"result": "Review passed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["result"] == "Review passed"
    assert completed.json()["finished_at"] is not None

    invalid_restart = client.post(f"/api/v1/tasks/{task['id']}/start", headers=headers)
    assert invalid_restart.status_code == 409

    audit = client.get("/api/v1/audit", headers=headers)
    actions = {event["action"] for event in audit.json()}
    assert {"TASK_CREATED", "TASK_STARTED", "TASK_COMPLETED"} <= actions


def test_ai_inference_task_runs_through_background_worker(client, db_session):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    model = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "worker-chat",
            "provider": "openai-compatible",
            "model_identifier": "test-model",
            "capabilities": ["chat"],
        },
    )
    assert model.status_code == 201

    prompt = "Summarize this in a sentence."
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Background inference",
            "work_type": "ai.inference",
            "work_payload": {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 64,
                "ignored_extra": "not persisted",
            },
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["work_type"] == "ai.inference"
    assert task["status"] == "PENDING"
    assert "work_payload" not in task
    work_item = db_session.get(TaskWorkItem, task["id"])
    assert work_item is not None
    assert "ignored_extra" not in work_item.payload

    assert process_next_work_item(
        db_session,
        worker_id="test-worker",
        provider=StubInferenceProvider(),
    )

    completed = client.get(f"/api/v1/tasks/{task['id']}", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["finished_at"] is not None
    assert '"content": "Hello from the model"' in completed.json()["result"]

    worker_audit = client.get("/api/v1/audit", headers=headers).json()
    task_details = [
        event["detail"]
        for event in worker_audit
        if event["resource_id"] == task["id"]
    ]
    assert all(prompt not in str(detail) for detail in task_details)

    rejected_manual_start = client.post(
        f"/api/v1/tasks/{task['id']}/start",
        headers=headers,
    )
    assert rejected_manual_start.status_code == 409


def test_worker_retries_transient_inference_failure(client, db_session):
    class FlakyProvider(StubInferenceProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ProviderTimeoutError("provider timed out")
            return super().generate(**kwargs)

    headers = auth_headers(role="operator", tenant_id="tenant-a")
    model = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "retry-chat",
            "provider": "openai-compatible",
            "model_identifier": "test-model",
            "capabilities": ["chat"],
        },
    )
    assert model.status_code == 201
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Retry inference",
            "work_type": "ai.inference",
            "work_payload": {
                "messages": [{"role": "user", "content": "Retry me"}],
            },
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    provider = FlakyProvider()
    now = datetime.now(timezone.utc)

    assert process_next_work_item(
        db_session,
        worker_id="test-worker",
        provider=provider,
        now=now,
    )
    pending = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert pending.json()["status"] == "IN_PROGRESS"
    assert pending.json()["finished_at"] is None

    assert process_next_work_item(
        db_session,
        worker_id="test-worker",
        provider=provider,
        now=now + timedelta(seconds=10),
    )
    completed = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert completed.json()["status"] == "COMPLETED"
    assert provider.calls == 2


def test_worker_rejects_invalid_jobs_and_honors_emergency_stop(client, db_session):
    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    invalid_requests = [
        {"title": "Missing type", "work_payload": {}},
        {"title": "Missing payload", "work_type": "ai.inference"},
        {
            "title": "Unsupported type",
            "work_type": "shell.command",
            "work_payload": {},
        },
        {
            "title": "Invalid inference",
            "work_type": "ai.inference",
            "work_payload": {"messages": [{"role": "user"}]},
        },
    ]
    for request in invalid_requests:
        response = client.post(
            "/api/v1/tasks",
            headers=operator_headers,
            json=request,
        )
        assert response.status_code == 422

    created = client.post(
        "/api/v1/tasks",
        headers=operator_headers,
        json={
            "title": "Wait during emergency stop",
            "work_type": "ai.inference",
            "work_payload": {
                "messages": [{"role": "user", "content": "Do not run yet"}],
            },
        },
    )
    assert created.status_code == 201

    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    stopped = client.post("/api/v1/emergency-stop", headers=owner_headers)
    assert stopped.status_code == 200
    assert not process_next_work_item(
        db_session,
        worker_id="test-worker",
        provider=StubInferenceProvider(),
    )
    pending = client.get(
        f"/api/v1/tasks/{created.json()['id']}",
        headers=operator_headers,
    )
    assert pending.json()["status"] == "PENDING"


def test_cancelled_worker_task_is_not_executed(client, db_session):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Cancelled inference",
            "work_type": "ai.inference",
            "work_payload": {
                "messages": [{"role": "user", "content": "Do not execute"}],
            },
        },
    )
    task_id = created.json()["id"]

    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert not process_next_work_item(
        db_session,
        worker_id="test-worker",
        provider=StubInferenceProvider(),
    )


def test_task_failure_and_cancellation_transitions(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    failed_task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Failing task"},
    ).json()
    client.post(f"/api/v1/tasks/{failed_task['id']}/start", headers=headers)

    failed = client.post(
        f"/api/v1/tasks/{failed_task['id']}/fail",
        headers=headers,
        json={"reason": "Upstream dependency unavailable"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"
    assert failed.json()["failure_reason"] == "Upstream dependency unavailable"

    cancelled_task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Cancelled task"},
    ).json()
    cancelled = client.post(
        f"/api/v1/tasks/{cancelled_task['id']}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["finished_at"] is not None

    invalid_cancel = client.post(
        f"/api/v1/tasks/{cancelled_task['id']}/cancel",
        headers=headers,
    )
    assert invalid_cancel.status_code == 409


def test_tasks_are_tenant_scoped_and_viewer_read_only(client):
    created = client.post(
        "/api/v1/tasks",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"title": "Tenant A task"},
    )
    task_id = created.json()["id"]

    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    listed = client.get("/api/v1/tasks?status=PENDING", headers=viewer_headers)
    assert listed.status_code == 200
    assert [task["id"] for task in listed.json()] == [task_id]

    denied_create = client.post(
        "/api/v1/tasks",
        headers=viewer_headers,
        json={"title": "Viewer cannot create"},
    )
    assert denied_create.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/tasks/{task_id}",
        headers=auth_headers(role="operator", tenant_id="tenant-b"),
    )
    assert cross_tenant.status_code == 404


def test_emergency_stop_blocks_task_creation_and_start(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/tasks",
        headers=owner_headers,
        json={"title": "Wait during stop"},
    )
    assert created.status_code == 201

    activated = client.post("/api/v1/emergency-stop", headers=owner_headers)
    assert activated.status_code == 200

    blocked_start = client.post(
        f"/api/v1/tasks/{created.json()['id']}/start",
        headers=owner_headers,
    )
    assert blocked_start.status_code == 409

    blocked_create = client.post(
        "/api/v1/tasks",
        headers=owner_headers,
        json={"title": "Blocked task"},
    )
    assert blocked_create.status_code == 409


def test_event_journal_filters_events_and_validates_enabled_source(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    registered = client.post(
        "/api/v1/systems",
        headers=owner_headers,
        json={"name": "event-source", "system_type": "integration"},
    )
    source_id = registered.json()["id"]
    enabled = client.patch(
        f"/api/v1/systems/{source_id}",
        headers=owner_headers,
        json={"status": "ENABLED"},
    )
    assert enabled.status_code == 200

    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    published = client.post(
        "/api/v1/events",
        headers=operator_headers,
        json={
            "event_type": "integration.sync.completed",
            "source_system_id": source_id,
            "payload": {"records": 12, "ok": True},
        },
    )
    assert published.status_code == 201
    event = published.json()
    assert event["payload"] == {"records": 12, "ok": True}

    filtered = client.get(
        "/api/v1/events?event_type=integration.sync.completed",
        headers=operator_headers,
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [event["id"]]

    viewer_read = client.get(
        "/api/v1/events",
        headers=auth_headers(role="viewer", tenant_id="tenant-a"),
    )
    assert viewer_read.status_code == 403

    audit = client.get("/api/v1/audit", headers=operator_headers)
    event_audit = next(
        entry for entry in audit.json() if entry["action"] == "EVENT_PUBLISHED"
    )
    assert event_audit["detail"] == {
        "event_type": "integration.sync.completed",
        "source_system_id": source_id,
        "webhook_delivery_count": 0,
    }


def test_event_journal_rejects_unavailable_sources_and_oversized_payloads(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    not_found = client.post(
        "/api/v1/events",
        headers=headers,
        json={
            "event_type": "integration.failed",
            "source_system_id": "00000000-0000-0000-0000-000000000000",
            "payload": {},
        },
    )
    assert not_found.status_code == 404

    oversized = client.post(
        "/api/v1/events",
        headers=headers,
        json={
            "event_type": "integration.payload",
            "payload": {"content": "x" * (64 * 1024)},
        },
    )
    assert oversized.status_code == 422


def test_tenant_configuration_upsert_access_and_delete(client):
    owner_a = auth_headers(role="owner", tenant_id="tenant-a")
    owner_b = auth_headers(role="owner", tenant_id="tenant-b")
    first = client.put(
        "/api/v1/config",
        headers=owner_a,
        json={"key": "runtime.max_retries", "value": 3},
    )
    assert first.status_code == 200
    config_id = first.json()["id"]
    assert first.json()["value"] == 3

    updated = client.put(
        "/api/v1/config",
        headers=owner_a,
        json={"key": "runtime.max_retries", "value": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == config_id
    assert updated.json()["value"] == 5

    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    listed = client.get("/api/v1/config", headers=operator_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["key"] == "runtime.max_retries"
    assert listed.json()[0]["value"] == 5

    viewer_read = client.get(
        "/api/v1/config",
        headers=auth_headers(role="viewer", tenant_id="tenant-a"),
    )
    assert viewer_read.status_code == 403

    denied_write = client.put(
        "/api/v1/config",
        headers=operator_headers,
        json={"key": "runtime.max_retries", "value": 6},
    )
    assert denied_write.status_code == 403

    other_tenant_list = client.get("/api/v1/config", headers=owner_b)
    assert other_tenant_list.status_code == 200
    assert other_tenant_list.json() == []
    cross_tenant_get = client.get(
        f"/api/v1/config/{config_id}",
        headers=owner_b,
    )
    assert cross_tenant_get.status_code == 404

    audit = client.get("/api/v1/audit", headers=operator_headers)
    config_events = [
        event for event in audit.json() if event["action"].startswith("CONFIGURATION_")
    ]
    assert {event["action"] for event in config_events} == {
        "CONFIGURATION_CREATED",
        "CONFIGURATION_UPDATED",
    }
    assert all("value" not in event["detail"] for event in config_events)

    deleted = client.delete(f"/api/v1/config/{config_id}", headers=owner_a)
    assert deleted.status_code == 204
    missing = client.get(f"/api/v1/config/{config_id}", headers=owner_a)
    assert missing.status_code == 404


def test_tenant_configuration_rejects_secret_keys_and_invalid_values(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    secret_key = client.put(
        "/api/v1/config",
        headers=owner_headers,
        json={"key": "provider.api_key", "value": "do-not-store"},
    )
    assert secret_key.status_code == 422

    null_value = client.put(
        "/api/v1/config",
        headers=owner_headers,
        json={"key": "runtime.enabled", "value": None},
    )
    assert null_value.status_code == 422

    oversized_value = client.put(
        "/api/v1/config",
        headers=owner_headers,
        json={"key": "runtime.large", "value": "x" * (32 * 1024)},
    )
    assert oversized_value.status_code == 422


def test_model_registry_and_routing(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")

    first = client.post(
        "/api/v1/models",
        headers=owner_headers,
        json={
            "name": "general-low",
            "provider": "openai",
            "model_identifier": "gpt-general-low",
            "capabilities": ["chat", "summarize"],
            "priority": 10,
        },
    )
    assert first.status_code == 201

    selected = client.post(
        "/api/v1/models",
        headers=owner_headers,
        json={
            "name": "reasoning-high",
            "provider": "anthropic",
            "model_identifier": "claude-reasoning",
            "capabilities": ["chat", "reason"],
            "priority": 100,
        },
    )
    assert selected.status_code == 201

    route = client.post(
        "/api/v1/models/route",
        headers=owner_headers,
        json={"capability": "chat"},
    )
    assert route.status_code == 200
    assert route.json()["name"] == "reasoning-high"

    provider_route = client.post(
        "/api/v1/models/route",
        headers=owner_headers,
        json={"capability": "chat", "provider": "openai"},
    )
    assert provider_route.status_code == 200
    assert provider_route.json()["name"] == "general-low"


def test_model_routing_tenant_isolation_and_disabled_status(client):
    owner_a = auth_headers(role="owner", tenant_id="tenant-a")
    owner_b = auth_headers(role="owner", tenant_id="tenant-b")

    created = client.post(
        "/api/v1/models",
        headers=owner_a,
        json={
            "name": "tenant-a-model",
            "provider": "local",
            "model_identifier": "local-a",
            "capabilities": ["embed"],
            "priority": 50,
        },
    )
    assert created.status_code == 201
    model_id = created.json()["id"]

    disabled = client.patch(
        f"/api/v1/models/{model_id}",
        headers=owner_a,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "DISABLED"

    no_route = client.post(
        "/api/v1/models/route",
        headers=owner_a,
        json={"capability": "embed"},
    )
    assert no_route.status_code == 404

    other_tenant = client.post(
        "/api/v1/models/route",
        headers=owner_b,
        json={"capability": "embed"},
    )
    assert other_tenant.status_code == 404


def test_viewer_cannot_create_or_update_models(client):
    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")

    created = client.post(
        "/api/v1/models",
        headers=viewer_headers,
        json={
            "name": "forbidden",
            "provider": "local",
            "model_identifier": "forbidden",
        },
    )
    assert created.status_code == 403


def test_model_discovery_and_health_status(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")

    created = client.post(
        "/api/v1/models",
        headers=owner_headers,
        json={
            "name": "catalog-model",
            "provider": "openai-compatible",
            "model_identifier": "model-a",
            "capabilities": ["chat"],
            "status": "ENABLED",
        },
    )
    assert created.status_code == 201
    model_id = created.json()["id"]

    provider = OpenAICompatibleProvider(
        Settings(
            ai_base_url="https://provider.test/v1",
            ai_api_key=Settings(ai_api_key="test-secret").ai_api_key,
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": [{"id": "model-a"}, {"id": "model-b"}]},
            )
            if str(request.url).endswith("/models")
            else httpx.Response(404)
        ),
    )
    app.dependency_overrides[get_inference_provider] = lambda: provider

    discovered = client.get(
        "/api/v1/models/catalog/discover",
        headers=owner_headers,
    )
    assert discovered.status_code == 200
    assert discovered.json()["model_identifiers"] == ["model-a", "model-b"]

    healthy = client.post(
        f"/api/v1/models/{model_id}/health",
        headers=owner_headers,
    )
    assert healthy.status_code == 200
    assert healthy.json()["health_status"] == "HEALTHY"
    assert healthy.json()["last_health_check_at"] is not None
    assert healthy.json()["health_error"] is None


def test_ai_inference_uses_registered_model_and_audits_without_prompt(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    registered = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
            "priority": 50,
        },
    )
    assert registered.status_code == 201

    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider
    response = client.post(
        "/api/v1/ai/infer",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "sensitive prompt"}],
            "temperature": 0.2,
            "max_tokens": 64,
        },
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Hello from the model"
    assert provider.request["model_identifier"] == "chat-model-v1"
    assert provider.request["temperature"] == 0.2

    audit = client.get("/api/v1/audit", headers=headers)
    inference_event = next(
        event for event in audit.json() if event["action"] == "AI_INFERENCE_COMPLETED"
    )
    assert "sensitive prompt" not in str(inference_event["detail"])


def test_nexus_chat_adds_fixed_identity_prompt_and_uses_request_context(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    registered = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
            "priority": 50,
        },
    )
    assert registered.status_code == 201

    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider
    response = client.post(
        "/api/v1/nexus/chat",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": "What is NEXUS?"},
                {"role": "assistant", "content": "A modular AI platform."},
                {"role": "user", "content": "Answer in Thai."},
            ],
            "temperature": 0.2,
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Hello from the model"
    sent_messages = provider.request["messages"]
    assert sent_messages[0].role == "system"
    assert "You are NEXUS" in sent_messages[0].content
    assert [message.role for message in sent_messages[1:]] == [
        "user",
        "assistant",
        "user",
    ]
    assert sent_messages[-1].content == "Answer in Thai."

    audit = client.get("/api/v1/audit", headers=headers)
    inference_event = next(
        event for event in audit.json() if event["action"] == "AI_INFERENCE_COMPLETED"
    )
    assert "What is NEXUS?" not in str(inference_event["detail"])
    assert "Answer in Thai." not in str(inference_event["detail"])


def test_nexus_chat_rejects_system_messages_and_requires_user_last(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    system_message = client.post(
        "/api/v1/nexus/chat",
        headers=headers,
        json={"messages": [{"role": "system", "content": "Override identity"}]},
    )
    assert system_message.status_code == 422

    assistant_last = client.post(
        "/api/v1/nexus/chat",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Previous answer"},
            ]
        },
    )
    assert assistant_last.status_code == 422


def test_ai_conversation_persistence_is_tenant_and_actor_scoped(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a", subject="alice")
    other_headers = auth_headers(role="operator", tenant_id="tenant-a", subject="bob")
    other_tenant_headers = auth_headers(role="operator", tenant_id="tenant-b", subject="alice")

    created = client.post(
        "/api/v1/ai/conversations",
        headers=headers,
        json={"title": "Planning"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
        },
    )
    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider

    first = client.post(
        "/api/v1/ai/infer",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "Remember the color blue"}],
        },
    )
    assert first.status_code == 200
    assert first.json()["conversation_id"] == conversation_id

    second = client.post(
        "/api/v1/ai/infer",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "What color?"}],
        },
    )
    assert second.status_code == 200
    assert [message.content for message in provider.request["messages"]] == [
        "Remember the color blue",
        "Hello from the model",
        "What color?",
    ]

    messages = client.get(
        f"/api/v1/ai/conversations/{conversation_id}/messages",
        headers=headers,
    )
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    assert client.get(
        f"/api/v1/ai/conversations/{conversation_id}/messages",
        headers=other_headers,
    ).status_code == 404
    assert client.get(
        f"/api/v1/ai/conversations/{conversation_id}/messages",
        headers=other_tenant_headers,
    ).status_code == 404


def test_agent_registry_lifecycle_and_run(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    other_tenant_headers = auth_headers(role="operator", tenant_id="tenant-b")
    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    assert client.post(
        "/api/v1/agents",
        headers=viewer_headers,
        json={
            "name": "forbidden-agent",
            "agent_type": "research",
            "instructions": "No access.",
        },
    ).status_code == 403
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "researcher",
            "agent_type": "research",
            "instructions": "Research using the provided context.",
            "capabilities": ["research"],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        },
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]
    assert created.json()["status"] == "REGISTERED"
    assert client.get("/api/v1/agents", headers=viewer_headers).status_code == 200
    assert client.get(
        f"/api/v1/agents/{agent_id}",
        headers=other_tenant_headers,
    ).status_code == 404

    client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
        },
    )
    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider

    disabled = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"prompt": "Do some research"},
    )
    assert disabled.status_code == 409
    assert not hasattr(provider, "request")

    enabled = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"status": "ENABLED"},
    )
    assert enabled.status_code == 200
    run = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"prompt": "private research request"},
    )
    assert run.status_code == 200
    assert run.json()["agent_id"] == agent_id
    assert provider.request["messages"][0].content == (
        "Research using the provided context."
    )
    assert provider.request["tools"][0].function.name == "lookup"

    audit_response = client.get("/api/v1/audit", headers=headers)
    agent_run_event = next(
        event
        for event in audit_response.json()
        if event["action"] == "AGENT_RUN_COMPLETED"
    )
    assert "private research request" not in str(agent_run_event["detail"])


def test_agent_orchestration_runs_only_requested_enabled_agents(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    agent_ids = []
    for name in ("researcher", "analyst"):
        created = client.post(
            "/api/v1/agents",
            headers=headers,
            json={
                "name": name,
                "agent_type": name,
                "instructions": f"You are the {name}.",
                "status": "ENABLED",
            },
        )
        assert created.status_code == 201
        agent_ids.append(created.json()["id"])
    client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
        },
    )
    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider

    result = client.post(
        "/api/v1/agents/orchestrate",
        headers=headers,
        json={"agent_ids": agent_ids, "prompt": "Review this proposal"},
    )
    assert result.status_code == 200
    assert [step["agent_id"] for step in result.json()["steps"]] == agent_ids
    assert len(result.json()["steps"]) == 2
    assert provider.request["messages"][0].content == "You are the analyst."


def test_knowledge_documents_are_versioned_and_searchable_within_tenant(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    other_tenant_headers = auth_headers(role="viewer", tenant_id="tenant-b")
    source_content = "Northstar project details. " * 80
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        json={
            "name": "northstar",
            "source": "manual://northstar",
            "content": source_content,
            "status": "ACTIVE",
        },
    )
    assert created.status_code == 201
    document_id = created.json()["id"]
    assert created.json()["current_version"] == 1

    content = client.get(
        f"/api/v1/knowledge/documents/{document_id}/content",
        headers=viewer_headers,
    )
    assert content.status_code == 200
    assert content.json()["content"] == source_content

    search = client.post(
        "/api/v1/knowledge/search",
        headers=viewer_headers,
        json={"query": "northstar project", "limit": 5},
    )
    assert search.status_code == 200
    assert search.json()["hits"]
    assert search.json()["hits"][0]["document_id"] == document_id
    assert search.json()["hits"][0]["score"] == 1.0
    assert client.post(
        "/api/v1/knowledge/search",
        headers=other_tenant_headers,
        json={"query": "northstar"},
    ).json()["hits"] == []

    updated = client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"content": "Revised starship launch facts.", "status": "ACTIVE"},
    )
    assert updated.status_code == 200
    assert updated.json()["current_version"] == 2
    revised_search = client.post(
        "/api/v1/knowledge/search",
        headers=headers,
        json={"query": "revised launch"},
    )
    assert revised_search.json()["hits"][0]["version"] == 2
    assert "Revised starship" in revised_search.json()["hits"][0]["text"]
    versions = client.get(
        f"/api/v1/knowledge/documents/{document_id}/versions",
        headers=viewer_headers,
    )
    assert versions.status_code == 200
    assert [version["version"] for version in versions.json()] == [1, 2]
    original_content = client.get(
        f"/api/v1/knowledge/documents/{document_id}/content?version=1",
        headers=viewer_headers,
    )
    assert original_content.json()["content"] == source_content
    assert client.post(
        "/api/v1/knowledge/search",
        headers=headers,
        json={"query": "northstar"},
    ).json()["hits"] == []

    audit_response = client.get("/api/v1/audit", headers=headers)
    knowledge_events = [
        event
        for event in audit_response.json()
        if event["action"].startswith("KNOWLEDGE_")
    ]
    assert knowledge_events
    assert source_content not in str(knowledge_events)

    deleted = client.delete(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert client.get(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
    ).status_code == 404


def test_knowledge_source_registry_is_tenant_scoped_and_audited(client):
    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    other_tenant_headers = auth_headers(role="viewer", tenant_id="tenant-b")

    created = client.post(
        "/api/v1/knowledge/sources",
        headers=owner_headers,
        json={
            "name": "OpenAlex",
            "url": "https://openalex.org",
            "source_type": "ACADEMIC_INDEX",
            "knowledge_domains": ["Computer Science", "Research"],
            "credibility": "S2",
            "status": "VERIFIED",
            "access_method": "API",
            "license": "CC0",
            "update_frequency": "DAILY",
            "security_risk": "LOW",
            "research_status": "APPROVED",
        },
    )
    assert created.status_code == 201
    source = created.json()
    source_id = source["id"]
    assert source["tenant_id"] == "tenant-a"
    assert source["credibility"] == "S2"
    assert source["last_verified_at"] is not None

    assert client.get(
        f"/api/v1/knowledge/sources/{source_id}",
        headers=viewer_headers,
    ).status_code == 200
    assert client.get(
        f"/api/v1/knowledge/sources/{source_id}",
        headers=other_tenant_headers,
    ).status_code == 404
    assert client.patch(
        f"/api/v1/knowledge/sources/{source_id}",
        headers=viewer_headers,
        json={"research_status": "IN_REVIEW"},
    ).status_code == 403

    updated = client.patch(
        f"/api/v1/knowledge/sources/{source_id}",
        headers=owner_headers,
        json={"status": "RESTRICTED", "security_risk": "HIGH"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "RESTRICTED"
    assert updated.json()["security_risk"] == "HIGH"

    listed = client.get(
        "/api/v1/knowledge/sources?status=RESTRICTED&credibility=S2",
        headers=viewer_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [source_id]

    audit_response = client.get("/api/v1/audit", headers=owner_headers)
    source_events = [
        event
        for event in audit_response.json()
        if event["action"].startswith("KNOWLEDGE_SOURCE_")
    ]
    assert {event["action"] for event in source_events} >= {
        "KNOWLEDGE_SOURCE_CREATED",
        "KNOWLEDGE_SOURCE_UPDATED",
    }

    assert client.delete(
        f"/api/v1/knowledge/sources/{source_id}",
        headers=owner_headers,
    ).status_code == 204
    assert client.get(
        f"/api/v1/knowledge/sources/{source_id}",
        headers=viewer_headers,
    ).status_code == 404


def test_knowledge_source_registry_rejects_duplicate_names_and_domains(client):
    headers = auth_headers(role="owner", tenant_id="tenant-a")
    payload = {
        "name": "Duplicate",
        "source_type": "DATABASE",
        "knowledge_domains": ["Science"],
        "access_method": "WEB",
    }
    assert client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        json=payload,
    ).status_code == 201
    assert client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        json=payload,
    ).status_code == 409
    assert client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        json={
            **payload,
            "name": "InvalidDomains",
            "knowledge_domains": ["Science", "Science"],
        },
    ).status_code == 422


def test_knowledge_drafts_are_hidden_and_registry_requires_manage_permission(client):
    operator_headers = auth_headers(role="operator", tenant_id="tenant-a")
    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    draft = client.post(
        "/api/v1/knowledge/documents",
        headers=operator_headers,
        json={
            "name": "draft",
            "source": "manual://draft",
            "content": "unpublished star map",
        },
    )
    assert draft.status_code == 201
    assert draft.json()["status"] == "DRAFT"
    assert client.post(
        "/api/v1/knowledge/search",
        headers=viewer_headers,
        json={"query": "star map"},
    ).json()["hits"] == []
    assert client.post(
        "/api/v1/knowledge/documents",
        headers=viewer_headers,
        json={
            "name": "forbidden",
            "source": "manual://forbidden",
            "content": "viewer cannot write",
        },
    ).status_code == 403


def test_intelligence_assessment_persists_results_with_tenant_access(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    viewer_headers = auth_headers(role="viewer", tenant_id="tenant-a")
    other_tenant_headers = auth_headers(role="viewer", tenant_id="tenant-b")
    payload = {
        "title": "Platform choice",
        "objective": "Choose a platform for private project context",
        "criteria": [
            {"name": "security", "weight": 0.7},
            {"name": "cost", "weight": 0.3},
        ],
        "alternatives": [
            {
                "name": "Managed",
                "scores": {"security": 90, "cost": 60},
                "risks": [
                    {"name": "Vendor lock-in", "probability": 3, "impact": 4}
                ],
            },
            {
                "name": "Self-hosted",
                "scores": {"security": 80, "cost": 75},
                "risks": [],
            },
        ],
    }

    created = client.post(
        "/api/v1/intelligence/assessments",
        headers=headers,
        json=payload,
    )
    assert created.status_code == 201
    assessment_id = created.json()["id"]
    assert created.json()["alternatives"][0]["name"] == "Managed"
    assert created.json()["alternatives"][0]["weighted_score"] == 81.0
    assert created.json()["alternatives"][0]["risk_score"] == 12

    detail = client.get(
        f"/api/v1/intelligence/assessments/{assessment_id}",
        headers=viewer_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["objective"] == payload["objective"]
    assert client.get(
        f"/api/v1/intelligence/assessments/{assessment_id}",
        headers=other_tenant_headers,
    ).status_code == 404
    assert client.get(
        "/api/v1/intelligence/assessments",
        headers=viewer_headers,
    ).json()[0]["criterion_count"] == 2

    viewer_create = client.post(
        "/api/v1/intelligence/assessments",
        headers=viewer_headers,
        json=payload,
    )
    assert viewer_create.status_code == 403

    audit_response = client.get("/api/v1/audit", headers=headers)
    assessment_event = next(
        event
        for event in audit_response.json()
        if event["action"] == "INTELLIGENCE_ASSESSMENT_CREATED"
    )
    assert payload["objective"] not in str(assessment_event["detail"])


def test_ai_inference_obeys_emergency_stop(client):
    headers = auth_headers(role="owner", tenant_id="tenant-a")
    client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
        },
    )
    client.post("/api/v1/emergency-stop", headers=headers)
    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider

    response = client.post(
        "/api/v1/ai/infer",
        headers=headers,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 409
    assert not hasattr(provider, "request")


def test_ai_inference_reports_missing_provider_credentials(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "chat-primary",
            "provider": "openai-compatible",
            "model_identifier": "chat-model-v1",
            "capabilities": ["chat"],
        },
    )
    app.dependency_overrides[get_inference_provider] = lambda: OpenAICompatibleProvider(
        Settings(ai_api_key=None)
    )

    response = client.post(
        "/api/v1/ai/infer",
        headers=headers,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI provider API key is not configured"
