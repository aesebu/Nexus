import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.models import AIModelStatus, CommandStatus, RegistryStatus, TaskStatus


class CommandCreate(BaseModel):
    type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    require_approval: bool = True


class CommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    type: str
    payload: dict[str, Any]
    status: CommandStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    result: str | None


class CommandPolicyCreate(BaseModel):
    command_type: str = Field(min_length=1, max_length=128)
    require_approval: bool = True
    require_different_approver: bool = True
    enabled: bool = True
    description: str | None = Field(default=None, max_length=500)
    approval_payload_keys: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("approval_payload_keys")
    @classmethod
    def validate_approval_payload_keys(cls, value: list[str]) -> list[str]:
        _validate_approval_payload_keys(value)
        return value


class CommandPolicyUpdate(BaseModel):
    require_approval: bool | None = None
    require_different_approver: bool | None = None
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    approval_payload_keys: list[str] | None = Field(default=None, max_length=64)

    @field_validator(
        "require_approval",
        "require_different_approver",
        "enabled",
        mode="before",
    )
    @classmethod
    def reject_null_boolean_flags(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Boolean policy fields cannot be null")
        return value

    @field_validator("approval_payload_keys")
    @classmethod
    def validate_approval_payload_keys(cls, value: list[str] | None) -> list[str]:
        if value is None:
            raise ValueError("Payload approval keys cannot be null")
        _validate_approval_payload_keys(value)
        return value


def _validate_approval_payload_keys(value: list[str]) -> None:
    if len(set(value)) != len(value):
        raise ValueError("Payload approval keys must be unique")
    for key in value:
        if (
            len(key) > 128
            or re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*",
                key,
            )
            is None
        ):
            raise ValueError("Payload approval keys must be valid dotted object paths")


class CommandPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    command_type: str
    require_approval: bool
    require_different_approver: bool
    enabled: bool
    description: str | None
    approval_payload_keys: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    updated_at: datetime


class SystemRegistrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    system_type: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    status: RegistryStatus = RegistryStatus.REGISTERED
    description: str | None = Field(default=None, max_length=500)


class SystemRegistrationUpdate(BaseModel):
    version: str | None = Field(default=None, max_length=64)
    capabilities: list[str] | None = None
    status: RegistryStatus | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("capabilities", "status", mode="before")
    @classmethod
    def reject_null_registry_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Registry fields cannot be null")
        return value


class SystemRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    system_type: str
    version: str | None
    capabilities: list[str]
    status: RegistryStatus
    description: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class TaskComplete(BaseModel):
    result: str | None = Field(default=None, max_length=10_000)


class TaskFail(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    title: str
    description: str | None
    status: TaskStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: str | None
    failure_reason: str | None


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=128)
    source_system_id: str | None = Field(default=None, min_length=36, max_length=36)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def limit_event_payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            serialized_size = len(
                json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Event payload must contain JSON-compatible data") from exc
        if serialized_size > 64 * 1024:
            raise ValueError("Event payload must not exceed 64 KiB")
        return value


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    event_type: str
    source_system_id: str | None
    payload: dict[str, Any]
    published_by: str
    created_at: datetime


class ConfigurationUpsert(BaseModel):
    key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    value: Any

    @field_validator("key")
    @classmethod
    def reject_secret_like_keys(cls, value: str) -> str:
        segments = set(re.split(r"[._-]+", value.lower()))
        if (
            segments
            & {"secret", "token", "password", "credential", "credentials"}
            or {"api", "key"} <= segments
            or {"access", "key"} <= segments
            or {"private", "key"} <= segments
        ):
            raise ValueError("Secret material must not be stored in tenant configuration")
        return value

    @field_validator("value")
    @classmethod
    def validate_configuration_value(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Configuration value cannot be null")
        try:
            serialized_size = len(
                json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
                .encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Configuration value must be JSON-compatible") from exc
        if serialized_size > 32 * 1024:
            raise ValueError("Configuration value must not exceed 32 KiB")
        return value


class ConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    key: str
    value: Any
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class SecretUpsert(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    value: SecretStr = Field(min_length=1, max_length=16 * 1024)


class SecretMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    detail: dict[str, Any]
    created_at: datetime


class EmergencyStopResponse(BaseModel):
    tenant_id: str
    active: bool
    activated_by: str | None
    activated_at: datetime | None


class AIModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    model_identifier: str = Field(min_length=1, max_length=256)
    capabilities: list[str] = Field(default_factory=list)
    status: AIModelStatus = AIModelStatus.ENABLED
    priority: int = Field(default=0, ge=0, le=1000)


class AIModelUpdate(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    model_identifier: str | None = Field(default=None, min_length=1, max_length=256)
    capabilities: list[str] | None = None
    status: AIModelStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)


class AIModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    provider: str
    model_identifier: str
    capabilities: list[str]
    status: AIModelStatus
    priority: int
    created_at: datetime
    updated_at: datetime


class ModelRouteRequest(BaseModel):
    capability: str = Field(min_length=1, max_length=128)
    provider: str | None = Field(default=None, min_length=1, max_length=128)


class ModelRouteResponse(BaseModel):
    model_id: str
    name: str
    provider: str
    model_identifier: str


class AIMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=32_000)


class InferenceRequest(BaseModel):
    messages: list[AIMessage] = Field(min_length=1, max_length=100)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=8192)


class NexusChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=32_000)


class NexusChatRequest(BaseModel):
    messages: list[NexusChatMessage] = Field(min_length=1, max_length=99)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=8192)

    @model_validator(mode="after")
    def requires_user_message_last(self) -> "NexusChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("The final chat message must be from the user")
        return self


class InferenceResponse(BaseModel):
    model_id: str
    model_name: str
    provider: str
    model_identifier: str
    content: str
    input_tokens: int | None
    output_tokens: int | None
