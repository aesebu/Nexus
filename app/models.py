import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class CommandStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AIModelStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"


class AIModelHealthStatus(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"


class RegistryStatus(str, enum.Enum):
    REGISTERED = "REGISTERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class ApplicationStatus(str, enum.Enum):
    REGISTERED = "REGISTERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class AgentStatus(str, enum.Enum):
    REGISTERED = "REGISTERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class KnowledgeDocumentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class KnowledgeSourceStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    VERIFIED = "VERIFIED"
    RESTRICTED = "RESTRICTED"
    DEPRECATED = "DEPRECATED"


class KnowledgeSourceCredibility(str, enum.Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkItemStatus(str, enum.Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IntegrationWebhookStatus(str, enum.Enum):
    REGISTERED = "REGISTERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[CommandStatus] = mapped_column(
        Enum(CommandStatus), default=CommandStatus.RECEIVED, index=True
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


class CommandPolicy(Base):
    __tablename__ = "command_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "command_type", name="uq_command_policy_tenant_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    command_type: Mapped[str] = mapped_column(String(128))
    require_approval: Mapped[bool] = mapped_column(default=True)
    require_different_approver: Mapped[bool] = mapped_column(default=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CommandPolicyPayloadRule(Base):
    __tablename__ = "command_policy_payload_rules"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "payload_key", name="uq_command_policy_payload_rule"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("command_policies.id", ondelete="CASCADE"), index=True
    )
    payload_key: Mapped[str] = mapped_column(String(128))


class CommandPolicyVersion(Base):
    __tablename__ = "command_policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_id", "version", name="uq_command_policy_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("command_policies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemRegistration(Base):
    __tablename__ = "system_registry"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_system_registry_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    system_type: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[RegistryStatus] = mapped_column(
        Enum(RegistryStatus), default=RegistryStatus.REGISTERED, index=True
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ApplicationRegistration(Base):
    __tablename__ = "application_registry"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "app_key",
            name="uq_application_registry_tenant_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    app_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus),
        default=ApplicationStatus.REGISTERED,
        index=True,
    )
    permission_scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ControlTask(Base):
    __tablename__ = "control_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, index=True
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskWorkItem(Base):
    __tablename__ = "task_work_items"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("control_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    work_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[WorkItemStatus] = mapped_column(
        Enum(WorkItemStatus), default=WorkItemStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'STOPPED')",
            name="ck_worker_heartbeat_status",
        ),
        Index(
            "ix_worker_heartbeats_status_last_seen_at",
            "status",
            "last_seen_at",
        ),
    )

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ControlEvent(Base):
    __tablename__ = "control_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    source_system_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    published_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrationWebhook(Base):
    __tablename__ = "integration_webhooks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_integration_webhook_tenant_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    target_url: Mapped[str] = mapped_column(String(2048))
    secret_name: Mapped[str] = mapped_column(String(128))
    event_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[IntegrationWebhookStatus] = mapped_column(
        Enum(IntegrationWebhookStatus),
        default=IntegrationWebhookStatus.REGISTERED,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IntegrationWebhookDelivery(Base):
    __tablename__ = "integration_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "webhook_id",
            "event_id",
            name="uq_integration_webhook_delivery_event",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("control_tasks.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    webhook_id: Mapped[str] = mapped_column(
        ForeignKey("integration_webhooks.id", ondelete="CASCADE"),
        index=True,
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("control_events.id", ondelete="CASCADE"),
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenantConfiguration(Base):
    __tablename__ = "tenant_configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_configuration_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[object] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenantSecret(Base):
    __tablename__ = "tenant_secrets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_secret_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmergencyStop(Base):
    __tablename__ = "emergency_stops"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    active: Mapped[bool] = mapped_column(default=False)
    activated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[str] = mapped_column(String(128))
    model_identifier: Mapped[str] = mapped_column(String(256))
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[AIModelStatus] = mapped_column(
        Enum(AIModelStatus), default=AIModelStatus.ENABLED, index=True
    )
    priority: Mapped[int] = mapped_column(default=0)
    health_status: Mapped[AIModelHealthStatus] = mapped_column(
        Enum(AIModelHealthStatus),
        default=AIModelHealthStatus.UNKNOWN,
        index=True,
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    health_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AIConversationMessage(Base):
    __tablename__ = "ai_conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_ai_conversation_message_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column()
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "ai_models.id",
            ondelete="SET NULL",
            name="fk_ai_conversation_messages_model_id_ai_models",
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIResponseFeedback(Base):
    __tablename__ = "ai_response_feedback"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "message_id",
            "submitted_by",
            name="uq_ai_response_feedback_actor_message",
        ),
        CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_ai_response_feedback_rating",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversation_messages.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    submitted_by: Mapped[str] = mapped_column(String(128))
    rating: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AIAgent(Base):
    __tablename__ = "ai_agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_ai_agent_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    agent_type: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instructions: Mapped[str] = mapped_column(Text)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    tools: Mapped[list[dict]] = mapped_column(JSON, default=list)
    preferred_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus), default=AgentStatus.REGISTERED, index=True
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_knowledge_document_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(500))
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        Enum(KnowledgeDocumentStatus),
        default=KnowledgeDocumentStatus.DRAFT,
        index=True,
    )
    current_version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version",
            name="uq_knowledge_document_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_chunk_version_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    chunk_index: Mapped[int] = mapped_column()
    start_offset: Mapped[int] = mapped_column()
    end_offset: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_knowledge_source_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(2_048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64))
    knowledge_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    credibility: Mapped[KnowledgeSourceCredibility] = mapped_column(
        Enum(KnowledgeSourceCredibility),
        default=KnowledgeSourceCredibility.S5,
        index=True,
    )
    status: Mapped[KnowledgeSourceStatus] = mapped_column(
        Enum(KnowledgeSourceStatus),
        default=KnowledgeSourceStatus.DISCOVERED,
        index=True,
    )
    access_method: Mapped[str] = mapped_column(String(64))
    license: Mapped[str | None] = mapped_column(String(500), nullable=True)
    update_frequency: Mapped[str | None] = mapped_column(String(64), nullable=True)
    security_risk: Mapped[str] = mapped_column(String(500), default="NOT_ASSESSED")
    research_status: Mapped[str] = mapped_column(String(64), default="PENDING")
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IntelligenceAssessment(Base):
    __tablename__ = "intelligence_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    result_snapshot: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AutomationWorkflowStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AutomationWorkflowRunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AutomationWorkflow(Base):
    __tablename__ = "automation_workflows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_automation_workflow_tenant_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    steps: Mapped[list[dict]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[AutomationWorkflowStatus] = mapped_column(
        Enum(AutomationWorkflowStatus),
        default=AutomationWorkflowStatus.DRAFT,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AutomationWorkflowRun(Base):
    __tablename__ = "automation_workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("control_tasks.id", ondelete="CASCADE"), unique=True, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("automation_workflows.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    workflow_version: Mapped[int] = mapped_column()
    input: Mapped[dict] = mapped_column(JSON)
    steps_snapshot: Mapped[list[dict]] = mapped_column(JSON)
    step_results: Mapped[list[dict]] = mapped_column(JSON, default=list)
    result_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[AutomationWorkflowRunStatus] = mapped_column(
        Enum(AutomationWorkflowRunStatus),
        default=AutomationWorkflowRunStatus.QUEUED,
        index=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
