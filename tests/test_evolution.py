from tests.conftest import auth_headers
from app.ai.providers import InferenceResult
from app.api.routes import get_inference_provider
from app.main import app
from app.models import AIConversation, AIConversationMessage


class StubInferenceProvider:
    provider_name = "openai-compatible"

    def __init__(self):
        self.model_identifier: str | None = None

    def generate(self, **kwargs):
        self.model_identifier = kwargs["model_identifier"]
        return InferenceResult(
            content="Generated response",
            input_tokens=8,
            output_tokens=4,
        )


def test_ai_response_feedback_is_scoped_updatable_and_aggregated(client):
    headers = auth_headers(role="operator", tenant_id="tenant-a", subject="alice")
    conversation = client.post(
        "/api/v1/ai/conversations",
        headers=headers,
        json={"title": "Feedback test"},
    )
    assert conversation.status_code == 201

    model = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": "feedback-model",
            "provider": "openai-compatible",
            "model_identifier": "feedback-model-v1",
            "capabilities": ["chat"],
        },
    )
    assert model.status_code == 201

    provider = StubInferenceProvider()
    app.dependency_overrides[get_inference_provider] = lambda: provider
    try:
        inference = client.post(
            "/api/v1/ai/infer",
            headers=headers,
            json={
                "conversation_id": conversation.json()["id"],
                "messages": [{"role": "user", "content": "Question"}],
            },
        )
    finally:
        app.dependency_overrides.pop(get_inference_provider, None)

    assert inference.status_code == 200
    response_message_id = inference.json()["response_message_id"]
    assert response_message_id
    assert inference.json()["model_id"] == model.json()["id"]
    assert provider.model_identifier == "feedback-model-v1"

    feedback_url = f"/api/v1/ai/messages/{response_message_id}/feedback"
    first = client.put(feedback_url, headers=headers, json={"rating": 4})
    assert first.status_code == 200
    assert first.json()["model_id"] == model.json()["id"]
    feedback_id = first.json()["id"]

    updated = client.put(feedback_url, headers=headers, json={"rating": 2})
    assert updated.status_code == 200
    assert updated.json()["id"] == feedback_id
    assert updated.json()["rating"] == 2

    assert client.put(feedback_url, headers=headers, json={"rating": 0}).status_code == 422
    assert client.put(
        feedback_url,
        headers=auth_headers(role="operator", tenant_id="tenant-a", subject="bob"),
        json={"rating": 5},
    ).status_code == 404
    assert client.put(
        feedback_url,
        headers=auth_headers(role="operator", tenant_id="tenant-b", subject="alice"),
        json={"rating": 5},
    ).status_code == 404
    assert client.put(
        feedback_url,
        headers=auth_headers(role="viewer", tenant_id="tenant-a", subject="alice"),
        json={"rating": 5},
    ).status_code == 403

    owner_headers = auth_headers(role="owner", tenant_id="tenant-a")
    summary = client.get("/api/v1/ai/evaluations/summary", headers=owner_headers)
    assert summary.status_code == 200
    assert summary.json() == [
        {
            "model_id": model.json()["id"],
            "model_name": "feedback-model",
            "provider": "openai-compatible",
            "feedback_count": 1,
            "average_rating": 2.0,
        }
    ]
    assert client.get(
        "/api/v1/ai/evaluations/summary",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
    ).status_code == 403
    assert client.get(
        "/api/v1/ai/evaluations/summary",
        headers=auth_headers(role="owner", tenant_id="tenant-b"),
    ).json() == []

    audit = client.get("/api/v1/audit", headers=owner_headers)
    feedback_audit = [
        event
        for event in audit.json()
        if event["action"].startswith("AI_RESPONSE_FEEDBACK_")
    ]
    assert len(feedback_audit) == 2
    assert all("content" not in event["detail"] for event in feedback_audit)


def test_legacy_ai_response_feedback_appears_as_unassigned(client, db_session):
    conversation = AIConversation(
        id="00000000-0000-0000-0000-000000000101",
        tenant_id="tenant-a",
        created_by="test-user",
    )
    message = AIConversationMessage(
        id="00000000-0000-0000-0000-000000000102",
        conversation_id=conversation.id,
        tenant_id="tenant-a",
        sequence=1,
        role="assistant",
        content="Legacy response",
    )
    db_session.add_all([conversation, message])
    db_session.commit()

    feedback = client.put(
        f"/api/v1/ai/messages/{message.id}/feedback",
        headers=auth_headers(role="operator", tenant_id="tenant-a"),
        json={"rating": 5},
    )
    assert feedback.status_code == 200
    assert feedback.json()["model_id"] is None

    summary = client.get(
        "/api/v1/ai/evaluations/summary",
        headers=auth_headers(role="owner", tenant_id="tenant-a"),
    )
    assert summary.json() == [
        {
            "model_id": None,
            "model_name": None,
            "provider": None,
            "feedback_count": 1,
            "average_rating": 5.0,
        }
    ]
