import json
import re
from datetime import datetime
from decimal import Decimal
import math
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.models import (
    AIModelHealthStatus,
    AIModelStatus,
    ApplicationStatus,
    AgentStatus,
    AutomationWorkflowRunStatus,
    AutomationWorkflowStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceCredibility,
    KnowledgeSourceStatus,
    IntegrationWebhookStatus,
    CommandStatus,
    RegistryStatus,
    TaskStatus,
)
from app.security import ROLE_PERMISSIONS


_KNOWN_APPLICATION_PERMISSION_SCOPES = set().union(*ROLE_PERMISSIONS.values())


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
    version: int = 1
    require_approval: bool
    require_different_approver: bool
    enabled: bool
    description: str | None
    approval_payload_keys: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    updated_at: datetime


class CommandPolicyVersionResponse(BaseModel):
    policy_id: str
    version: int
    snapshot: dict[str, Any]
    changed_by: str
    created_at: datetime


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


class ApplicationRegistrationCreate(BaseModel):
    app_key: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    )
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    status: ApplicationStatus = ApplicationStatus.REGISTERED
    permission_scopes: list[str] = Field(default_factory=list, max_length=64)
    data_scopes: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("permission_scopes")
    @classmethod
    def validate_permission_scopes(cls, value: list[str]) -> list[str]:
        _validate_application_permission_scopes(value)
        return value

    @field_validator("data_scopes")
    @classmethod
    def validate_data_scopes(cls, value: list[str]) -> list[str]:
        _validate_application_data_scopes(value)
        return value


class ApplicationRegistrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    status: ApplicationStatus | None = None
    permission_scopes: list[str] | None = Field(default=None, max_length=64)
    data_scopes: list[str] | None = Field(default=None, max_length=64)

    @field_validator(
        "name",
        "status",
        "permission_scopes",
        "data_scopes",
        mode="before",
    )
    @classmethod
    def reject_null_application_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Application fields cannot be null")
        return value

    @field_validator("permission_scopes")
    @classmethod
    def validate_permission_scopes(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is not None:
            _validate_application_permission_scopes(value)
        return value

    @field_validator("data_scopes")
    @classmethod
    def validate_data_scopes(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            _validate_application_data_scopes(value)
        return value

    @model_validator(mode="after")
    def requires_update_field(self) -> "ApplicationRegistrationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one application field must be provided")
        return self


def _validate_application_permission_scopes(value: list[str]) -> None:
    if len(set(value)) != len(value):
        raise ValueError("Application permission scopes must be unique")
    unknown_scopes = set(value) - _KNOWN_APPLICATION_PERMISSION_SCOPES
    if unknown_scopes:
        raise ValueError(
            "Application permission scopes must match known NEXUS permissions"
        )


def _validate_application_data_scopes(value: list[str]) -> None:
    if len(set(value)) != len(value):
        raise ValueError("Application data scopes must be unique")
    for scope in value:
        if (
            len(scope) > 128
            or re.fullmatch(
                r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*",
                scope,
            )
            is None
        ):
            raise ValueError("Application data scopes must be valid scope identifiers")


class ApplicationRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    app_key: str
    name: str
    description: str | None
    status: ApplicationStatus
    permission_scopes: list[str]
    data_scopes: list[str]
    created_by: str
    created_at: datetime
    updated_at: datetime


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
    work_type: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: str | None
    failure_reason: str | None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    work_type: Literal["ai.inference"] | None = None
    work_payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_work_payload(self) -> "TaskCreate":
        if self.work_type is None:
            if self.work_payload is not None:
                raise ValueError("work_payload requires a supported work_type")
            return self
        if self.work_payload is None:
            raise ValueError("work_payload is required for ai.inference tasks")

        try:
            request = InferenceRequest.model_validate(self.work_payload)
            self.work_payload = request.model_dump(mode="json")
            serialized = json.dumps(
                self.work_payload,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except ValidationError as exc:
            raise ValueError("work_payload is not a valid inference request") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError("work_payload must contain JSON-compatible data") from exc
        if len(serialized.encode("utf-8")) > 64 * 1024:
            raise ValueError("work_payload must not exceed 64 KiB")
        return self


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=128)
    source_system_id: str | None = Field(default=None, min_length=36, max_length=36)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def limit_event_payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            serialized_size = len(
                json.dumps(
                    value,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
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


class IntegrationWebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_url: str = Field(min_length=8, max_length=2048)
    secret_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    event_types: list[str] = Field(min_length=1, max_length=64)
    status: IntegrationWebhookStatus = IntegrationWebhookStatus.REGISTERED

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value: list[str]) -> list[str]:
        _validate_webhook_event_types(value)
        return value


class IntegrationWebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    target_url: str | None = Field(default=None, min_length=8, max_length=2048)
    secret_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    event_types: list[str] | None = Field(default=None, min_length=1, max_length=64)
    status: IntegrationWebhookStatus | None = None

    @field_validator(
        "name",
        "target_url",
        "secret_name",
        "event_types",
        "status",
        mode="before",
    )
    @classmethod
    def reject_null_webhook_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Webhook fields cannot be null")
        return value

    @field_validator("event_types")
    @classmethod
    def validate_event_types(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is not None:
            _validate_webhook_event_types(value)
        return value

    @model_validator(mode="after")
    def requires_update_field(self) -> "IntegrationWebhookUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one webhook field must be provided")
        return self


def _validate_webhook_event_types(value: list[str]) -> None:
    if len(set(value)) != len(value):
        raise ValueError("Webhook event types must be unique")
    for event_type in value:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", event_type) is None:
            raise ValueError("Webhook event types must be valid event identifiers")


class IntegrationWebhookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    target_url: str
    secret_name: str
    event_types: list[str]
    status: IntegrationWebhookStatus
    created_by: str
    created_at: datetime
    updated_at: datetime


class IntegrationWebhookDeliveryResponse(BaseModel):
    id: str
    webhook_id: str
    event_id: str
    task_id: str
    status: TaskStatus
    attempts: int
    failure_reason: str | None
    created_at: datetime
    finished_at: datetime | None


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
    health_status: AIModelHealthStatus
    last_health_check_at: datetime | None
    health_error: str | None
    created_at: datetime
    updated_at: datetime


class AIModelDiscoveryResponse(BaseModel):
    provider: str
    model_identifiers: list[str]


class AIModelHealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    provider: str
    model_identifier: str
    health_status: AIModelHealthStatus
    last_health_check_at: datetime | None
    health_error: str | None


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


class AIToolFunction(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2_000)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AITool(BaseModel):
    type: Literal["function"]
    function: AIToolFunction


class AIToolCall(BaseModel):
    id: str
    type: Literal["function"]
    function: dict[str, str]


class AIResponseFormat(BaseModel):
    type: Literal["json_object", "json_schema"]
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_schema(self) -> "AIResponseFormat":
        if self.type == "json_schema":
            if self.json_schema is None:
                raise ValueError("json_schema is required for json_schema response format")
            if not isinstance(self.json_schema.get("schema"), dict):
                raise ValueError("json_schema.schema must be an object")
        return self


class InferenceRequest(BaseModel):
    messages: list[AIMessage] = Field(min_length=1, max_length=100)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)
    response_format: AIResponseFormat | None = None
    tools: list[AITool] = Field(default_factory=list, max_length=32)


class NexusChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=32_000)


class NexusChatRequest(BaseModel):
    messages: list[NexusChatMessage] = Field(min_length=1, max_length=99)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)
    response_format: AIResponseFormat | None = None
    tools: list[AITool] = Field(default_factory=list, max_length=32)

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
    conversation_id: str | None = None
    tool_calls: list[AIToolCall] = Field(default_factory=list)
    structured_output: dict[str, Any] | list[Any] | None = None


class AIConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class AIConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    created_by: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class AIConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    tenant_id: str
    sequence: int
    role: str
    content: str
    created_at: datetime


class AIAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    agent_type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    description: str | None = Field(default=None, max_length=500)
    instructions: str = Field(min_length=1, max_length=12_000)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    tools: list[AITool] = Field(default_factory=list, max_length=16)
    preferred_provider: str | None = Field(default=None, min_length=1, max_length=128)
    status: AgentStatus = AgentStatus.REGISTERED

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 128 for item in value):
            raise ValueError("Capabilities must be non-empty and at most 128 characters")
        if len(set(value)) != len(value):
            raise ValueError("Capabilities must be unique")
        return value

    @field_validator("tools")
    @classmethod
    def unique_tool_names(cls, value: list[AITool]) -> list[AITool]:
        names = [tool.function.name for tool in value]
        if len(set(names)) != len(names):
            raise ValueError("Tool names must be unique")
        return value


class AIAgentUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, min_length=1, max_length=12_000)
    capabilities: list[str] | None = Field(default=None, max_length=32)
    tools: list[AITool] | None = Field(default=None, max_length=16)
    preferred_provider: str | None = Field(default=None, min_length=1, max_length=128)
    status: AgentStatus | None = None

    @field_validator("capabilities", "tools", "status", mode="before")
    @classmethod
    def reject_null_agent_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Agent fields cannot be null")
        return value

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if any(not item or len(item) > 128 for item in value):
            raise ValueError("Capabilities must be non-empty and at most 128 characters")
        if len(set(value)) != len(value):
            raise ValueError("Capabilities must be unique")
        return value

    @field_validator("tools")
    @classmethod
    def unique_tool_names(cls, value: list[AITool] | None) -> list[AITool] | None:
        if value is None:
            return value
        names = [tool.function.name for tool in value]
        if len(set(names)) != len(names):
            raise ValueError("Tool names must be unique")
        return value


class AIAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    agent_type: str
    description: str | None
    instructions: str
    capabilities: list[str]
    tools: list[AITool]
    preferred_provider: str | None
    status: AgentStatus
    created_by: str
    created_at: datetime
    updated_at: datetime


class AIAgentRunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32_000)
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)
    response_format: AIResponseFormat | None = None


class AIAgentRunResponse(BaseModel):
    agent_id: str
    agent_name: str
    inference: InferenceResponse


class AIAgentOrchestrationRequest(BaseModel):
    agent_ids: list[str] = Field(min_length=1, max_length=5)
    prompt: str = Field(min_length=1, max_length=32_000)

    @field_validator("agent_ids")
    @classmethod
    def unique_agent_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Agent IDs must be unique")
        return value


class AIAgentOrchestrationStep(BaseModel):
    agent_id: str
    agent_name: str
    content: str


class AIAgentOrchestrationResponse(BaseModel):
    steps: list[AIAgentOrchestrationStep]


class KnowledgeDocumentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    source: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=256 * 1024)
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.DRAFT


class KnowledgeDocumentUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=256 * 1024)
    status: KnowledgeDocumentStatus | None = None

    @field_validator("source", "content", "status", mode="before")
    @classmethod
    def reject_null_document_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Document fields cannot be null")
        return value

    @model_validator(mode="after")
    def requires_update_field(self) -> "KnowledgeDocumentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one document field must be provided")
        return self


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    description: str | None
    source: str
    status: KnowledgeDocumentStatus
    current_version: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentContentResponse(BaseModel):
    document: KnowledgeDocumentResponse
    version: int
    content: str


class KnowledgeDocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    version: int
    created_by: str
    created_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1_000)
    document_ids: list[str] | None = Field(default=None, max_length=50)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Document IDs must be unique")
        return value

    @field_validator("query")
    @classmethod
    def validate_query_terms(cls, value: str) -> str:
        value = value.strip()
        terms = re.findall(r"\w+", value)
        if not terms:
            raise ValueError("Query must contain searchable text")
        if len(terms) > 32:
            raise ValueError("Query cannot contain more than 32 search terms")
        return value


class KnowledgeSearchHit(BaseModel):
    document_id: str
    document_name: str
    source: str
    version: int
    chunk_index: int
    text: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    hits: list[KnowledgeSearchHit]


class KnowledgeSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2_048)
    source_type: str = Field(min_length=1, max_length=64)
    knowledge_domains: list[str] = Field(default_factory=list, max_length=50)
    credibility: KnowledgeSourceCredibility = KnowledgeSourceCredibility.S5
    status: KnowledgeSourceStatus = KnowledgeSourceStatus.DISCOVERED
    access_method: str = Field(min_length=1, max_length=64)
    license: str | None = Field(default=None, max_length=500)
    update_frequency: str | None = Field(default=None, max_length=64)
    security_risk: str = Field(default="NOT_ASSESSED", max_length=500)
    research_status: str = Field(default="PENDING", max_length=64)

    @field_validator("knowledge_domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        normalized = [domain.strip() for domain in value if domain.strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Knowledge domains must be unique")
        return normalized


class KnowledgeSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2_048)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    knowledge_domains: list[str] | None = Field(default=None, max_length=50)
    credibility: KnowledgeSourceCredibility | None = None
    status: KnowledgeSourceStatus | None = None
    access_method: str | None = Field(default=None, min_length=1, max_length=64)
    license: str | None = Field(default=None, max_length=500)
    update_frequency: str | None = Field(default=None, max_length=64)
    security_risk: str | None = Field(default=None, max_length=500)
    research_status: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def requires_update_field(self) -> "KnowledgeSourceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one source field must be provided")
        return self

    @field_validator("knowledge_domains")
    @classmethod
    def validate_domains(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        normalized = [domain.strip() for domain in value if domain.strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Knowledge domains must be unique")
        return normalized


class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    url: str | None
    source_type: str
    knowledge_domains: list[str]
    credibility: KnowledgeSourceCredibility
    status: KnowledgeSourceStatus
    access_method: str
    license: str | None
    update_frequency: str | None
    security_risk: str
    research_status: str
    last_verified_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class DecisionCriterion(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(gt=0, le=1, strict=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Criterion name cannot be blank")
        return value

    @field_validator("weight")
    @classmethod
    def require_finite_weight(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Criterion weight must be finite")
        return value


class DecisionRiskFactor(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    probability: int = Field(ge=1, le=5, strict=True)
    impact: int = Field(ge=1, le=5, strict=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Risk factor name cannot be blank")
        return value


class DecisionAlternative(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scores: dict[str, int]
    risks: list[DecisionRiskFactor] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Alternative name cannot be blank")
        return value

    @field_validator("scores", mode="before")
    @classmethod
    def validate_scores(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not value:
            raise ValueError("Alternative scores cannot be empty")
        if any(
            not isinstance(score, int)
            or isinstance(score, bool)
            or not 0 <= score <= 100
            for score in value.values()
        ):
            raise ValueError("Criterion scores must be between 0 and 100")
        return value

    @field_validator("risks")
    @classmethod
    def unique_risk_names(
        cls, value: list[DecisionRiskFactor]
    ) -> list[DecisionRiskFactor]:
        names = [risk.name.casefold() for risk in value]
        if len(set(names)) != len(names):
            raise ValueError("Risk factor names must be unique per alternative")
        return value


class DecisionAssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4_000)
    criteria: list[DecisionCriterion] = Field(min_length=1, max_length=20)
    alternatives: list[DecisionAlternative] = Field(min_length=2, max_length=10)

    @field_validator("title", "objective")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text fields cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_assessment(self) -> "DecisionAssessmentCreate":
        criterion_names = [criterion.name.casefold() for criterion in self.criteria]
        if len(set(criterion_names)) != len(criterion_names):
            raise ValueError("Criterion names must be unique")
        weight_total = sum(
            (Decimal(str(criterion.weight)) for criterion in self.criteria),
            Decimal(0),
        )
        if abs(weight_total - Decimal(1)) > Decimal("0.000001"):
            raise ValueError("Criterion weights must sum to 1")

        alternative_names = [alternative.name.casefold() for alternative in self.alternatives]
        if len(set(alternative_names)) != len(alternative_names):
            raise ValueError("Alternative names must be unique")
        expected = {criterion.name for criterion in self.criteria}
        for alternative in self.alternatives:
            if set(alternative.scores) != expected:
                raise ValueError(
                    "Each alternative must provide exactly one score per criterion"
                )
        return self


class DecisionCriterionResult(BaseModel):
    name: str
    weight: float
    score: int
    contribution: float


class DecisionRiskResult(BaseModel):
    name: str
    probability: int
    impact: int
    exposure: int
    level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]


class DecisionAlternativeResult(BaseModel):
    name: str
    rank: int
    weighted_score: float
    criteria: list[DecisionCriterionResult]
    risk_score: int
    risk_level: Literal["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL"]
    risks: list[DecisionRiskResult]


class DecisionAssessmentResponse(BaseModel):
    id: str
    title: str
    objective: str
    criteria: list[DecisionCriterion]
    alternatives: list[DecisionAlternativeResult]
    created_by: str
    created_at: datetime


class DecisionAssessmentListItem(BaseModel):
    id: str
    title: str
    created_by: str
    created_at: datetime
    criterion_count: int
    alternative_count: int


class WorkflowCondition(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$",
    )
    equals: Any

    @field_validator("equals")
    @classmethod
    def validate_condition_value(cls, value: Any) -> Any:
        try:
            serialized = json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Workflow condition value must be JSON-compatible") from exc
        if len(serialized.encode("utf-8")) > 4 * 1024:
            raise ValueError("Workflow condition value must not exceed 4 KiB")
        return value


class AutomationWorkflowStep(BaseModel):
    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    prompt: str = Field(min_length=1, max_length=10_000)
    system_prompt: str | None = Field(default=None, max_length=4_000)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    response_format: AIResponseFormat | None = None
    condition: WorkflowCondition | None = None


class AutomationWorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    steps: list[AutomationWorkflowStep] = Field(min_length=1, max_length=10)
    status: AutomationWorkflowStatus = AutomationWorkflowStatus.DRAFT

    @field_validator("steps")
    @classmethod
    def unique_step_ids(
        cls, value: list[AutomationWorkflowStep]
    ) -> list[AutomationWorkflowStep]:
        step_ids = [step.id for step in value]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("Workflow step IDs must be unique")
        return value


class AutomationWorkflowUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    steps: list[AutomationWorkflowStep] | None = Field(
        default=None,
        min_length=1,
        max_length=10,
    )
    status: AutomationWorkflowStatus | None = None

    @field_validator("steps", "status", mode="before")
    @classmethod
    def reject_null_workflow_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Workflow fields cannot be null")
        return value

    @field_validator("steps")
    @classmethod
    def unique_step_ids(
        cls, value: list[AutomationWorkflowStep] | None
    ) -> list[AutomationWorkflowStep] | None:
        if value is None:
            return value
        step_ids = [step.id for step in value]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("Workflow step IDs must be unique")
        return value

    @model_validator(mode="after")
    def requires_update_field(self) -> "AutomationWorkflowUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one workflow field must be provided")
        return self


class AutomationWorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    description: str | None
    steps: list[AutomationWorkflowStep]
    version: int
    status: AutomationWorkflowStatus
    created_by: str
    created_at: datetime
    updated_at: datetime


class AutomationWorkflowRunCreate(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    delay_seconds: int = Field(default=0, ge=0, le=30 * 24 * 60 * 60)

    @field_validator("input")
    @classmethod
    def validate_input_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            serialized = json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Workflow input must be JSON-compatible") from exc
        if len(serialized.encode("utf-8")) > 16 * 1024:
            raise ValueError("Workflow input must not exceed 16 KiB")
        return value


class AutomationWorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    workflow_version: int
    task_id: str
    status: AutomationWorkflowRunStatus
    input: dict[str, Any]
    step_results: list[dict[str, Any]]
    result: dict[str, Any] | None
    failure_reason: str | None
    scheduled_at: datetime
    created_by: str
    created_at: datetime
