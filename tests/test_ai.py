import json

import httpx
import pytest
from pydantic import SecretStr

from app.ai.providers import (
    OpenAICompatibleProvider,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderResponseError,
)
from app.core.config import Settings
from app.schemas import AIMessage


def test_openai_compatible_provider_sends_chat_request_and_parses_usage():
    received = {}

    def handle(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["authorization"] = request.headers["Authorization"]
        received["payload"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatibleProvider(
        Settings(
            ai_base_url="https://provider.test/v1",
            ai_api_key=SecretStr("test-secret"),
        ),
        transport=httpx.MockTransport(handle),
    )
    result = provider.generate(
        model_identifier="model-x",
        messages=[AIMessage(role="user", content="question")],
        temperature=0.4,
        max_tokens=50,
    )

    assert received["url"] == "https://provider.test/v1/chat/completions"
    assert received["authorization"] == "Bearer test-secret"
    assert json.loads(received["payload"])["model"] == "model-x"
    assert result.content == "answer"
    assert result.input_tokens == 12
    assert result.output_tokens == 3


def test_provider_requires_api_key():
    assert Settings(ai_api_key="").ai_api_key is None
    provider = OpenAICompatibleProvider(Settings(ai_api_key=None))

    with pytest.raises(ProviderNotConfiguredError):
        provider.generate(
            model_identifier="model-x",
            messages=[AIMessage(role="user", content="question")],
            temperature=0.4,
            max_tokens=50,
        )


def test_provider_surfaces_upstream_errors_and_invalid_responses():
    failing_provider = OpenAICompatibleProvider(
        Settings(ai_api_key=SecretStr("test-secret")),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, json={"error": "rate limited"})
        ),
    )
    with pytest.raises(ProviderRequestError, match="HTTP 429"):
        failing_provider.generate(
            model_identifier="model-x",
            messages=[AIMessage(role="user", content="question")],
            temperature=0.4,
            max_tokens=50,
        )

    invalid_provider = OpenAICompatibleProvider(
        Settings(ai_api_key=SecretStr("test-secret")),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
    )
    with pytest.raises(ProviderResponseError, match="invalid response"):
        invalid_provider.generate(
            model_identifier="model-x",
            messages=[AIMessage(role="user", content="question")],
            temperature=0.4,
            max_tokens=50,
        )


def test_openai_compatible_provider_discovers_model_catalog():
    received = {}

    def handle(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "model-b"},
                    {"id": "model-a"},
                    {"id": "model-b"},
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        Settings(
            ai_base_url="https://provider.test/v1",
            ai_api_key=SecretStr("test-secret"),
        ),
        transport=httpx.MockTransport(handle),
    )

    assert provider.discover_models() == ["model-a", "model-b"]
    assert received["url"] == "https://provider.test/v1/models"
    assert received["authorization"] == "Bearer test-secret"


def test_provider_catalog_rejects_invalid_response():
    provider = OpenAICompatibleProvider(
        Settings(ai_api_key=SecretStr("test-secret")),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": "invalid"})
        ),
    )

    with pytest.raises(ProviderResponseError, match="invalid model catalog"):
        provider.discover_models()
