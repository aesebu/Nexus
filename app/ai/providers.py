from dataclasses import dataclass
import json
from typing import Protocol

import httpx

from app.core.config import Settings
from app.schemas import AIMessage


class AIProviderError(Exception):
    pass


class ProviderNotConfiguredError(AIProviderError):
    pass


class UnsupportedProviderError(AIProviderError):
    pass


class ProviderTimeoutError(AIProviderError):
    pass


class ProviderRequestError(AIProviderError):
    pass


class ProviderResponseError(AIProviderError):
    pass


@dataclass(frozen=True)
class InferenceResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    tool_calls: list[dict] | None = None
    structured_output: dict | list | None = None


class InferenceProvider(Protocol):
    provider_name: str

    def generate(
        self,
        *,
        model_identifier: str,
        messages: list[AIMessage],
        temperature: float,
        max_tokens: int,
        response_format: object | None = None,
        tools: list[object] | None = None,
    ) -> InferenceResult: ...

    def discover_models(self) -> list[str]: ...


class OpenAICompatibleProvider:
    provider_name = "openai-compatible"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def generate(
        self,
        *,
        model_identifier: str,
        messages: list[AIMessage],
        temperature: float,
        max_tokens: int,
        response_format: object | None = None,
        tools: list[object] | None = None,
    ) -> InferenceResult:
        if self._settings.ai_api_key is None:
            raise ProviderNotConfiguredError("AI provider API key is not configured")

        payload = {
            "model": model_identifier,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = (
                response_format.model_dump(exclude_none=True)
            )
        if tools:
            payload["tools"] = [tool.model_dump(exclude_none=True) for tool in tools]
        try:
            with httpx.Client(
                timeout=30.0,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._settings.ai_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": (
                            f"Bearer {self._settings.ai_api_key.get_secret_value()}"
                        ),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("AI provider request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderRequestError(
                f"AI provider returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError("AI provider request failed") from exc

        try:
            body = response.json()
            message = body["choices"][0]["message"]
            content = message.get("content")
            raw_tool_calls = message.get("tool_calls")
            tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
            usage = body.get("usage", {})
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise TypeError("response content is not a string")
            if not isinstance(tool_calls, list):
                raise TypeError("tool calls are not a list")
            structured_output = None
            if response_format is not None:
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise ProviderResponseError(
                        "AI provider returned invalid structured output"
                    ) from exc
                if not isinstance(parsed, (dict, list)):
                    raise ProviderResponseError(
                        "AI provider returned invalid structured output"
                    )
                structured_output = parsed
            if input_tokens is not None and (
                not isinstance(input_tokens, int) or isinstance(input_tokens, bool)
            ):
                raise TypeError("prompt token count is not an integer")
            if output_tokens is not None and (
                not isinstance(output_tokens, int) or isinstance(output_tokens, bool)
            ):
                raise TypeError("completion token count is not an integer")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError("AI provider returned an invalid response") from exc

        return InferenceResult(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=tool_calls,
            structured_output=structured_output,
        )

    def discover_models(self) -> list[str]:
        if self._settings.ai_api_key is None:
            raise ProviderNotConfiguredError("AI provider API key is not configured")

        try:
            with httpx.Client(
                timeout=30.0,
                transport=self._transport,
            ) as client:
                response = client.get(
                    f"{self._settings.ai_base_url.rstrip('/')}/models",
                    headers={
                        "Authorization": (
                            f"Bearer {self._settings.ai_api_key.get_secret_value()}"
                        ),
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("AI provider request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderRequestError(
                f"AI provider returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError("AI provider request failed") from exc

        try:
            body = response.json()
            data = body["data"]
            if not isinstance(data, list):
                raise TypeError("model data is not a list")
            identifiers = []
            for item in data:
                identifier = item["id"]
                if not isinstance(identifier, str) or not identifier:
                    raise TypeError("model identifier is invalid")
                identifiers.append(identifier)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError("AI provider returned an invalid model catalog") from exc
        return sorted(set(identifiers))
