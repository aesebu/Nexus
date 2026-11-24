from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.ai.providers import InferenceResult, ProviderTimeoutError
from app.models import AutomationWorkflowRun, TaskWorkItem, WorkItemStatus
from app.schemas import AutomationWorkflowCreate, AutomationWorkflowRunCreate
from app.worker import process_next_work_item
from tests.conftest import auth_headers


def _workflow_payload(*, status: str = "DRAFT") -> dict:
    return {
        "name": "Document review",
        "status": status,
        "steps": [
            {"id": "summarize", "prompt": "Summarize"},
            {
                "id": "approve",
                "prompt": "Check approval",
                "condition": {"path": "approved", "equals": True},
            },
        ],
    }


def _create_active_workflow(client, headers, *, steps=None):
    payload = _workflow_payload(status="ACTIVE")
    if steps is not None:
        payload["steps"] = steps
    response = client.post("/api/v1/workflows", headers=headers, json=payload)
    assert response.status_code == 201
    return response.json()


def test_workflow_lifecycle_is_tenant_scoped_and_snapshots_delayed_runs(
    client,
    db_session,
):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    created = client.post(
        "/api/v1/workflows",
        headers=headers,
        json=_workflow_payload(),
    )
    assert created.status_code == 201
    workflow = created.json()
    assert workflow["version"] == 1
    assert workflow["status"] == "DRAFT"
    assert client.post(
        f"/api/v1/workflows/{workflow['id']}/runs",
        headers=headers,
        json={"input": {"approved": True}},
    ).status_code == 409

    activated = client.patch(
        f"/api/v1/workflows/{workflow['id']}",
        headers=headers,
        json={"status": "ACTIVE"},
    )
    assert activated.status_code == 200
    scheduled = client.post(
        f"/api/v1/workflows/{workflow['id']}/runs",
        headers=headers,
        json={"input": {"approved": True}, "delay_seconds": 60},
    )
    assert scheduled.status_code == 202
    run = scheduled.json()
    assert run["status"] == "QUEUED"
    assert run["workflow_version"] == 1
    assert run["step_results"] == []

    changed = client.patch(
        f"/api/v1/workflows/{workflow['id']}",
        headers=headers,
        json={
            "steps": [
                {"id": "summarize", "prompt": "Updated prompt"},
                {
                    "id": "approve",
                    "prompt": "Check approval",
                    "condition": {"path": "approved", "equals": True},
                },
            ]
        },
    )
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    persisted_run = db_session.get(AutomationWorkflowRun, run["id"])
    assert persisted_run is not None
    assert persisted_run.workflow_version == 1
    assert persisted_run.steps_snapshot[0]["prompt"] == "Summarize"

    other_tenant_headers = auth_headers(role="operator", tenant_id="tenant-b")
    assert client.get(
        f"/api/v1/workflows/{workflow['id']}",
        headers=other_tenant_headers,
    ).status_code == 404
    assert client.get(
        f"/api/v1/workflow-runs/{run['id']}",
        headers=other_tenant_headers,
    ).status_code == 404

    cancelled = client.post(
        f"/api/v1/tasks/{run['task_id']}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert client.get(
        f"/api/v1/workflow-runs/{run['id']}",
        headers=headers,
    ).json()["status"] == "CANCELLED"
    assert db_session.get(TaskWorkItem, run["task_id"]).status == WorkItemStatus.CANCELLED


def test_workflow_worker_skips_conditions_and_resumes_completed_steps(
    client,
    db_session,
):
    headers = auth_headers(role="operator", tenant_id="tenant-a")
    model = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "workflow-chat",
            "provider": "openai-compatible",
            "model_identifier": "test-model",
            "capabilities": ["chat"],
        },
    )
    assert model.status_code == 201
    workflow = _create_active_workflow(
        client,
        headers,
        steps=[
            {"id": "first", "prompt": "First step"},
            {"id": "second", "prompt": "Second step"},
            {
                "id": "skipped",
                "prompt": "Should not run",
                "condition": {"path": "approved", "equals": True},
            },
        ],
    )
    run_response = client.post(
        f"/api/v1/workflows/{workflow['id']}/runs",
        headers=headers,
        json={"input": {"approved": False}},
    )
    assert run_response.status_code == 202
    run = run_response.json()

    class FlakyProvider:
        provider_name = "openai-compatible"

        def __init__(self):
            self.prompts = []
            self.failed_second_step = False

        def generate(self, **kwargs):
            prompt = kwargs["messages"][-1].content
            self.prompts.append(prompt)
            if "Second step" in prompt and not self.failed_second_step:
                self.failed_second_step = True
                raise ProviderTimeoutError("temporary timeout")
            return InferenceResult(
                content=f"Result {len(self.prompts)}",
                input_tokens=3,
                output_tokens=2,
            )

    provider = FlakyProvider()
    assert process_next_work_item(
        db_session,
        worker_id="workflow-worker",
        provider=provider,
    )
    partially_done = client.get(
        f"/api/v1/workflow-runs/{run['id']}",
        headers=headers,
    ).json()
    assert partially_done["status"] == "IN_PROGRESS"
    assert [item["step_id"] for item in partially_done["step_results"]] == ["first"]

    assert process_next_work_item(
        db_session,
        worker_id="workflow-worker",
        provider=provider,
        now=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    completed = client.get(
        f"/api/v1/workflow-runs/{run['id']}",
        headers=headers,
    ).json()
    assert completed["status"] == "COMPLETED"
    assert [item["status"] for item in completed["result"]["steps"]] == [
        "COMPLETED",
        "COMPLETED",
        "SKIPPED",
    ]
    assert sum("First step" in prompt for prompt in provider.prompts) == 1
    assert sum("Second step" in prompt for prompt in provider.prompts) == 2
    assert all("Should not run" not in prompt for prompt in provider.prompts)


def test_workflow_schemas_bound_conditions_and_json_input():
    with pytest.raises(ValidationError):
        AutomationWorkflowCreate.model_validate(
            {
                **_workflow_payload(status="ACTIVE"),
                "steps": [
                    {"id": "duplicate", "prompt": "First"},
                    {"id": "duplicate", "prompt": "Second"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        AutomationWorkflowCreate.model_validate(
            {
                **_workflow_payload(status="ACTIVE"),
                "steps": [
                    {
                        "id": "bad",
                        "prompt": "Bad condition",
                        "condition": {"path": "approved", "equals": float("nan")},
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        AutomationWorkflowRunCreate.model_validate(
            {"input": {"text": "x" * (16 * 1024 + 1)}}
        )
