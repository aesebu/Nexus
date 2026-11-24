import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.providers import (
    InferenceProvider,
    OpenAICompatibleProvider,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
    UnsupportedProviderError,
)
from app.ai.assistant import build_nexus_messages
from app.intelligence.decision import analyze_decision
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    AIModel,
    AIModelHealthStatus,
    AIModelStatus,
    AIConversation,
    AIConversationMessage,
    AIAgent,
    AgentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeDocumentVersion,
    KnowledgeSource,
    KnowledgeSourceStatus,
    ApplicationRegistration,
    ApplicationStatus,
    IntegrationWebhook,
    IntegrationWebhookDelivery,
    IntegrationWebhookStatus,
    IntelligenceAssessment,
    AutomationWorkflow,
    AutomationWorkflowRun,
    AutomationWorkflowRunStatus,
    AutomationWorkflowStatus,
    AuditEvent,
    Command,
    CommandPolicy,
    CommandPolicyPayloadRule,
    CommandPolicyVersion,
    CommandStatus,
    TenantConfiguration,
    ControlEvent,
    ControlTask,
    EmergencyStop,
    RegistryStatus,
    SystemRegistration,
    TaskStatus,
    TaskWorkItem,
    TenantSecret,
    WorkItemStatus,
)
from app.schemas import (
    AIModelCreate,
    AIMessage,
    AIModelDiscoveryResponse,
    AIModelHealthResponse,
    AIModelResponse,
    AIModelUpdate,
    AIConversationCreate,
    AIConversationMessageResponse,
    AIConversationResponse,
    AIAgentCreate,
    AIAgentUpdate,
    AIAgentResponse,
    AIAgentRunRequest,
    AIAgentRunResponse,
    AIAgentOrchestrationRequest,
    AIAgentOrchestrationResponse,
    AIAgentOrchestrationStep,
    AITool,
    KnowledgeDocumentContentResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentVersionResponse,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeSourceUpdate,
    ApplicationRegistrationCreate,
    ApplicationRegistrationResponse,
    ApplicationRegistrationUpdate,
    IntegrationWebhookCreate,
    IntegrationWebhookDeliveryResponse,
    IntegrationWebhookResponse,
    IntegrationWebhookUpdate,
    DecisionAssessmentCreate,
    DecisionAssessmentListItem,
    DecisionAssessmentResponse,
    AutomationWorkflowCreate,
    AutomationWorkflowResponse,
    AutomationWorkflowUpdate,
    AutomationWorkflowRunCreate,
    AutomationWorkflowRunResponse,
    AuditResponse,
    CommandCreate,
    CommandPolicyCreate,
    CommandPolicyResponse,
    CommandPolicyUpdate,
    CommandPolicyVersionResponse,
    CommandResponse,
    ConfigurationResponse,
    ConfigurationUpsert,
    EmergencyStopResponse,
    EventCreate,
    EventResponse,
    InferenceRequest,
    InferenceResponse,
    ModelRouteRequest,
    ModelRouteResponse,
    NexusChatRequest,
    SystemRegistrationCreate,
    SystemRegistrationResponse,
    SystemRegistrationUpdate,
    TaskComplete,
    TaskCreate,
    TaskFail,
    TaskResponse,
    SecretMetadataResponse,
    SecretUpsert,
)
from app.security import require_permission
from app.secrets import SecretStoreError, encrypt_secret
from app.integrations.webhooks import WebhookConfigurationError, validate_webhook_destination

router = APIRouter()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def audit(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    detail: dict,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            detail=detail,
        )
    )


def emergency_stop(db: Session, tenant_id: str) -> EmergencyStop:
    stop = db.scalar(
        select(EmergencyStop)
        .where(EmergencyStop.tenant_id == tenant_id)
        .with_for_update()
    )
    if stop is None:
        stop = EmergencyStop(tenant_id=tenant_id, active=False)
        db.add(stop)
        db.flush()
    return stop


def _command_policy_response(
    db: Session,
    policy: CommandPolicy,
) -> CommandPolicyResponse:
    payload_keys = list(
        db.scalars(
            select(CommandPolicyPayloadRule.payload_key)
            .where(CommandPolicyPayloadRule.policy_id == policy.id)
            .order_by(CommandPolicyPayloadRule.payload_key.asc())
        )
    )
    latest_version = db.scalar(
        select(CommandPolicyVersion)
        .where(CommandPolicyVersion.policy_id == policy.id)
        .order_by(CommandPolicyVersion.version.desc())
        .limit(1)
    )
    return CommandPolicyResponse.model_validate(policy).model_copy(
        update={
            "approval_payload_keys": payload_keys,
            "version": latest_version.version if latest_version is not None else 1,
        }
    )


def _policy_snapshot(policy: CommandPolicy, payload_keys: list[str]) -> dict[str, Any]:
    return {
        "command_type": policy.command_type,
        "require_approval": policy.require_approval,
        "require_different_approver": policy.require_different_approver,
        "enabled": policy.enabled,
        "description": policy.description,
        "approval_payload_keys": sorted(payload_keys),
    }


def _latest_policy_version(db: Session, policy_id: str) -> CommandPolicyVersion | None:
    return db.scalar(
        select(CommandPolicyVersion)
        .where(CommandPolicyVersion.policy_id == policy_id)
        .order_by(CommandPolicyVersion.version.desc())
        .limit(1)
    )


def _store_policy_version(
    db: Session,
    *,
    policy: CommandPolicy,
    snapshot: dict[str, Any],
    changed_by: str,
    version: int,
) -> CommandPolicyVersion:
    policy_version = CommandPolicyVersion(
        policy_id=policy.id,
        version=version,
        snapshot=snapshot,
        changed_by=changed_by,
    )
    db.add(policy_version)
    return policy_version


def _payload_has_path(payload: dict[str, Any], path: str) -> bool:
    current: Any = payload
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


@router.post(
    "/policies/commands",
    response_model=CommandPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_command_policy(
    request: CommandPolicyCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.policy.manage")),
) -> CommandPolicyResponse:
    actor, tenant_id = identity
    existing = db.scalar(
        select(CommandPolicy).where(
            CommandPolicy.tenant_id == tenant_id,
            CommandPolicy.command_type == request.command_type,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Command policy already exists")

    policy = CommandPolicy(
        tenant_id=tenant_id,
        command_type=request.command_type,
        require_approval=request.require_approval,
        require_different_approver=request.require_different_approver,
        enabled=request.enabled,
        description=request.description,
        created_by=actor,
    )
    try:
        db.add(policy)
        db.flush()
        db.add_all(
            CommandPolicyPayloadRule(policy_id=policy.id, payload_key=payload_key)
            for payload_key in request.approval_payload_keys
        )
        snapshot = _policy_snapshot(policy, request.approval_payload_keys)
        _store_policy_version(
            db,
            policy=policy,
            snapshot=snapshot,
            changed_by=actor,
            version=1,
        )
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="COMMAND_POLICY_CREATED",
            resource_type="CommandPolicy",
            resource_id=policy.id,
            outcome="SUCCESS",
            detail={
                "command_type": policy.command_type,
                "require_approval": policy.require_approval,
                "require_different_approver": policy.require_different_approver,
                "enabled": policy.enabled,
                "approval_payload_keys": request.approval_payload_keys,
                "version": 1,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Command policy already exists",
        ) from exc
    db.refresh(policy)
    return _command_policy_response(db, policy)


@router.get("/policies/commands", response_model=list[CommandPolicyResponse])
def list_command_policies(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.policy.read")),
) -> list[CommandPolicyResponse]:
    _actor, tenant_id = identity
    policies = list(
        db.scalars(
            select(CommandPolicy)
            .where(CommandPolicy.tenant_id == tenant_id)
            .order_by(CommandPolicy.command_type.asc())
        )
    )
    return [_command_policy_response(db, policy) for policy in policies]


@router.get(
    "/policies/commands/{policy_id}/versions",
    response_model=list[CommandPolicyVersionResponse],
)
def list_command_policy_versions(
    policy_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.policy.read")),
) -> list[CommandPolicyVersionResponse]:
    _actor, tenant_id = identity
    policy = db.scalar(
        select(CommandPolicy).where(
            CommandPolicy.id == policy_id,
            CommandPolicy.tenant_id == tenant_id,
        )
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="Command policy not found")

    versions = list(
        db.scalars(
            select(CommandPolicyVersion)
            .where(CommandPolicyVersion.policy_id == policy.id)
            .order_by(CommandPolicyVersion.version.asc())
        )
    )
    if versions:
        return [
            CommandPolicyVersionResponse(
                policy_id=version.policy_id,
                version=version.version,
                snapshot=version.snapshot,
                changed_by=version.changed_by,
                created_at=version.created_at,
            )
            for version in versions
        ]

    payload_keys = list(
        db.scalars(
            select(CommandPolicyPayloadRule.payload_key)
            .where(CommandPolicyPayloadRule.policy_id == policy.id)
            .order_by(CommandPolicyPayloadRule.payload_key.asc())
        )
    )
    return [
        CommandPolicyVersionResponse(
            policy_id=policy.id,
            version=1,
            snapshot=_policy_snapshot(policy, payload_keys),
            changed_by=policy.created_by,
            created_at=policy.created_at,
        )
    ]


@router.patch(
    "/policies/commands/{policy_id}",
    response_model=CommandPolicyResponse,
)
def update_command_policy(
    policy_id: str,
    request: CommandPolicyUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.policy.manage")),
) -> CommandPolicyResponse:
    actor, tenant_id = identity
    policy = db.scalar(
        select(CommandPolicy).where(
            CommandPolicy.id == policy_id,
            CommandPolicy.tenant_id == tenant_id,
        ).with_for_update()
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="Command policy not found")

    updates = request.model_dump(exclude_unset=True)
    payload_keys = updates.pop("approval_payload_keys", None)
    current_payload_keys = list(
        db.scalars(
            select(CommandPolicyPayloadRule.payload_key)
            .where(CommandPolicyPayloadRule.policy_id == policy.id)
            .order_by(CommandPolicyPayloadRule.payload_key.asc())
        )
    )
    previous_snapshot = _policy_snapshot(policy, current_payload_keys)
    latest_version = _latest_policy_version(db, policy.id)
    current_version = latest_version.version if latest_version is not None else 1
    if latest_version is None:
        _store_policy_version(
            db,
            policy=policy,
            snapshot=previous_snapshot,
            changed_by=policy.created_by,
            version=1,
        )

    for field, value in updates.items():
        setattr(policy, field, value)

    updated_payload_keys = (
        payload_keys if payload_keys is not None else current_payload_keys
    )
    if payload_keys is not None:
        db.execute(
            delete(CommandPolicyPayloadRule).where(
                CommandPolicyPayloadRule.policy_id == policy.id
            )
        )
        db.add_all(
            CommandPolicyPayloadRule(policy_id=policy.id, payload_key=payload_key)
            for payload_key in payload_keys
        )

    updated_snapshot = _policy_snapshot(policy, updated_payload_keys)
    if updated_snapshot != previous_snapshot:
        current_version += 1
        _store_policy_version(
            db,
            policy=policy,
            snapshot=updated_snapshot,
            changed_by=actor,
            version=current_version,
        )

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="COMMAND_POLICY_UPDATED",
        resource_type="CommandPolicy",
        resource_id=policy.id,
        outcome="SUCCESS",
        detail={
            "fields": sorted(
                [*updates, *(["approval_payload_keys"] if payload_keys is not None else [])]
            ),
            "version": current_version,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Command policy changed concurrently; retry the request",
        ) from exc
    db.refresh(policy)
    return _command_policy_response(db, policy)


@router.post(
    "/systems",
    response_model=SystemRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_system(
    request: SystemRegistrationCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.system.manage")),
) -> SystemRegistration:
    actor, tenant_id = identity
    existing = db.scalar(
        select(SystemRegistration).where(
            SystemRegistration.tenant_id == tenant_id,
            SystemRegistration.name == request.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="System name already exists")

    system = SystemRegistration(
        tenant_id=tenant_id,
        name=request.name,
        system_type=request.system_type,
        version=request.version,
        capabilities=request.capabilities,
        status=request.status,
        description=request.description,
        created_by=actor,
    )
    try:
        db.add(system)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="SYSTEM_REGISTERED",
            resource_type="SystemRegistration",
            resource_id=system.id,
            outcome="SUCCESS",
            detail={
                "name": system.name,
                "system_type": system.system_type,
                "status": system.status.value,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="System name already exists",
        ) from exc
    db.refresh(system)
    return system


@router.get("/systems", response_model=list[SystemRegistrationResponse])
def list_systems(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.system.read")),
) -> list[SystemRegistration]:
    _actor, tenant_id = identity
    return list(
        db.scalars(
            select(SystemRegistration)
            .where(SystemRegistration.tenant_id == tenant_id)
            .order_by(SystemRegistration.name.asc())
        )
    )


@router.get("/systems/{system_id}", response_model=SystemRegistrationResponse)
def get_system(
    system_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.system.read")),
) -> SystemRegistration:
    _actor, tenant_id = identity
    system = db.scalar(
        select(SystemRegistration).where(
            SystemRegistration.id == system_id,
            SystemRegistration.tenant_id == tenant_id,
        )
    )
    if system is None:
        raise HTTPException(status_code=404, detail="System not found")
    return system


@router.patch("/systems/{system_id}", response_model=SystemRegistrationResponse)
def update_system(
    system_id: str,
    request: SystemRegistrationUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.system.manage")),
) -> SystemRegistration:
    actor, tenant_id = identity
    system = db.scalar(
        select(SystemRegistration).where(
            SystemRegistration.id == system_id,
            SystemRegistration.tenant_id == tenant_id,
        )
    )
    if system is None:
        raise HTTPException(status_code=404, detail="System not found")

    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(system, field, value)

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="SYSTEM_UPDATED",
        resource_type="SystemRegistration",
        resource_id=system.id,
        outcome="SUCCESS",
        detail={"fields": sorted(updates)},
    )
    db.commit()
    db.refresh(system)
    return system


@router.post(
    "/applications",
    response_model=ApplicationRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_application(
    request: ApplicationRegistrationCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.application.manage")),
) -> ApplicationRegistration:
    actor, tenant_id = identity
    application = ApplicationRegistration(
        tenant_id=tenant_id,
        app_key=request.app_key,
        name=request.name,
        description=request.description,
        status=request.status,
        permission_scopes=request.permission_scopes,
        data_scopes=request.data_scopes,
        created_by=actor,
    )
    try:
        db.add(application)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="APPLICATION_REGISTERED",
            resource_type="ApplicationRegistration",
            resource_id=application.id,
            outcome="SUCCESS",
            detail={
                "app_key": application.app_key,
                "status": application.status.value,
                "permission_scope_count": len(application.permission_scopes),
                "data_scope_count": len(application.data_scopes),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Application key already exists",
        ) from exc
    db.refresh(application)
    return application


@router.get(
    "/applications",
    response_model=list[ApplicationRegistrationResponse],
)
def list_applications(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.application.read")),
    application_status: ApplicationStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ApplicationRegistration]:
    _actor, tenant_id = identity
    statement = select(ApplicationRegistration).where(
        ApplicationRegistration.tenant_id == tenant_id
    )
    if application_status is not None:
        statement = statement.where(
            ApplicationRegistration.status == application_status
        )
    return list(
        db.scalars(
            statement.order_by(ApplicationRegistration.app_key.asc())
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationRegistrationResponse,
)
def get_application(
    application_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.application.read")),
) -> ApplicationRegistration:
    _actor, tenant_id = identity
    application = db.scalar(
        select(ApplicationRegistration).where(
            ApplicationRegistration.id == application_id,
            ApplicationRegistration.tenant_id == tenant_id,
        )
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationRegistrationResponse,
)
def update_application(
    application_id: str,
    request: ApplicationRegistrationUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.application.manage")),
) -> ApplicationRegistration:
    actor, tenant_id = identity
    application = db.scalar(
        select(ApplicationRegistration)
        .where(
            ApplicationRegistration.id == application_id,
            ApplicationRegistration.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(application, field, value)
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="APPLICATION_UPDATED",
        resource_type="ApplicationRegistration",
        resource_id=application.id,
        outcome="SUCCESS",
        detail={
            "fields": sorted(updates),
            "permission_scope_count": len(application.permission_scopes),
            "data_scope_count": len(application.data_scopes),
        },
    )
    db.commit()
    db.refresh(application)
    return application


def control_task_for_tenant(
    db: Session,
    *,
    task_id: str,
    tenant_id: str,
) -> ControlTask:
    task = db.scalar(
        select(ControlTask).where(
            ControlTask.id == task_id,
            ControlTask.tenant_id == tenant_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def task_response(db: Session, task: ControlTask) -> TaskResponse:
    work_item = db.get(TaskWorkItem, task.id)
    return TaskResponse.model_validate(task).model_copy(
        update={"work_type": work_item.work_type if work_item is not None else None}
    )


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    request: TaskCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.manage")),
) -> TaskResponse:
    actor, tenant_id = identity
    if emergency_stop(db, tenant_id).active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    task = ControlTask(
        tenant_id=tenant_id,
        title=request.title,
        description=request.description,
        status=TaskStatus.PENDING,
        created_by=actor,
    )
    db.add(task)
    db.flush()
    if request.work_type is not None:
        if request.work_payload is None:
            raise HTTPException(status_code=422, detail="work_payload is required")
        db.add(
            TaskWorkItem(
                task_id=task.id,
                tenant_id=tenant_id,
                work_type=request.work_type,
                payload=request.work_payload,
                status=WorkItemStatus.PENDING,
            )
        )
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="TASK_CREATED",
        resource_type="ControlTask",
        resource_id=task.id,
        outcome="SUCCESS",
        detail={
            "status": task.status.value,
            "work_type": request.work_type,
        },
    )
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.read")),
    task_status: TaskStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[TaskResponse]:
    _actor, tenant_id = identity
    statement = select(ControlTask).where(ControlTask.tenant_id == tenant_id)
    if task_status is not None:
        statement = statement.where(ControlTask.status == task_status)
    statement = (
        statement.order_by(ControlTask.created_at.desc()).offset(offset).limit(limit)
    )
    return [task_response(db, task) for task in db.scalars(statement)]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.read")),
) -> TaskResponse:
    _actor, tenant_id = identity
    task = control_task_for_tenant(db, task_id=task_id, tenant_id=tenant_id)
    return task_response(db, task)


@router.post("/tasks/{task_id}/start", response_model=TaskResponse)
def start_task(
    task_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.manage")),
) -> TaskResponse:
    actor, tenant_id = identity
    task = db.scalar(
        select(ControlTask)
        .where(ControlTask.id == task_id, ControlTask.tenant_id == tenant_id)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if db.get(TaskWorkItem, task.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="Worker-managed tasks can only be started by the background worker",
        )
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot start from {task.status.value}",
        )
    if emergency_stop(db, tenant_id).active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="TASK_STARTED",
        resource_type="ControlTask",
        resource_id=task.id,
        outcome="SUCCESS",
        detail={"status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@router.post("/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    task_id: str,
    request: TaskComplete,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.manage")),
) -> TaskResponse:
    actor, tenant_id = identity
    task = db.scalar(
        select(ControlTask)
        .where(ControlTask.id == task_id, ControlTask.tenant_id == tenant_id)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if db.get(TaskWorkItem, task.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="Worker-managed tasks are completed by the background worker",
        )
    if task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot complete from {task.status.value}",
        )

    task.status = TaskStatus.COMPLETED
    task.result = request.result
    task.finished_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="TASK_COMPLETED",
        resource_type="ControlTask",
        resource_id=task.id,
        outcome="SUCCESS",
        detail={"status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@router.post("/tasks/{task_id}/fail", response_model=TaskResponse)
def fail_task(
    task_id: str,
    request: TaskFail,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.manage")),
) -> TaskResponse:
    actor, tenant_id = identity
    task = db.scalar(
        select(ControlTask)
        .where(ControlTask.id == task_id, ControlTask.tenant_id == tenant_id)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if db.get(TaskWorkItem, task.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="Worker-managed tasks are failed by the background worker",
        )
    if task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot fail from {task.status.value}",
        )

    task.status = TaskStatus.FAILED
    task.failure_reason = request.reason
    task.finished_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="TASK_FAILED",
        resource_type="ControlTask",
        resource_id=task.id,
        outcome="FAILED",
        detail={"status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.task.manage")),
) -> TaskResponse:
    actor, tenant_id = identity
    existing_task = db.scalar(
        select(ControlTask)
        .where(
            ControlTask.id == task_id,
            ControlTask.tenant_id == tenant_id,
        )
    )
    if existing_task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    work_item = db.scalar(
        select(TaskWorkItem)
        .where(TaskWorkItem.task_id == existing_task.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    task = db.scalar(
        select(ControlTask)
        .where(
            ControlTask.id == task_id,
            ControlTask.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot cancel from {task.status.value}",
        )

    task.status = TaskStatus.CANCELLED
    task.finished_at = utcnow()
    if work_item is not None:
        work_item.status = WorkItemStatus.CANCELLED
        work_item.claimed_by = None
        work_item.lease_expires_at = None
    workflow_run = db.scalar(
        select(AutomationWorkflowRun)
        .where(AutomationWorkflowRun.task_id == task.id)
        .with_for_update()
    )
    if workflow_run is not None:
        workflow_run.status = AutomationWorkflowRunStatus.CANCELLED
        workflow_run.failure_reason = None
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="TASK_CANCELLED",
        resource_type="ControlTask",
        resource_id=task.id,
        outcome="SUCCESS",
        detail={"status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def publish_event(
    request: EventCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.event.publish")),
) -> ControlEvent:
    actor, tenant_id = identity
    if request.source_system_id is not None:
        source = db.scalar(
            select(SystemRegistration).where(
                SystemRegistration.id == request.source_system_id,
                SystemRegistration.tenant_id == tenant_id,
                SystemRegistration.status == RegistryStatus.ENABLED,
            )
        )
        if source is None:
            raise HTTPException(
                status_code=404,
                detail="Enabled source system not found",
            )

    event = ControlEvent(
        tenant_id=tenant_id,
        event_type=request.event_type,
        source_system_id=request.source_system_id,
        payload=request.payload,
        published_by=actor,
    )
    db.add(event)
    db.flush()
    subscriptions = list(
        db.scalars(
            select(IntegrationWebhook).where(
                IntegrationWebhook.tenant_id == tenant_id,
                IntegrationWebhook.status == IntegrationWebhookStatus.ENABLED,
            )
        )
    )
    delivery_count = 0
    for subscription in subscriptions:
        if event.event_type not in subscription.event_types:
            continue
        task = ControlTask(
            tenant_id=tenant_id,
            title=f"Webhook delivery: {subscription.name}",
            description=f"Delivery for event {event.id}",
            status=TaskStatus.PENDING,
            created_by=actor,
        )
        db.add(task)
        db.flush()
        delivery = IntegrationWebhookDelivery(
            task_id=task.id,
            webhook_id=subscription.id,
            event_id=event.id,
            tenant_id=tenant_id,
        )
        db.add(delivery)
        db.flush()
        db.add(
            TaskWorkItem(
                task_id=task.id,
                tenant_id=tenant_id,
                work_type="integration.webhook",
                payload={"delivery_id": delivery.id},
                status=WorkItemStatus.PENDING,
            )
        )
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="WEBHOOK_DELIVERY_QUEUED",
            resource_type="IntegrationWebhookDelivery",
            resource_id=delivery.id,
            outcome="SUCCESS",
            detail={
                "webhook_id": subscription.id,
                "event_id": event.id,
                "event_type": event.event_type,
                "task_id": task.id,
            },
        )
        delivery_count += 1
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="EVENT_PUBLISHED",
        resource_type="ControlEvent",
        resource_id=event.id,
        outcome="SUCCESS",
        detail={
            "event_type": event.event_type,
            "source_system_id": event.source_system_id,
            "webhook_delivery_count": delivery_count,
        },
    )
    db.commit()
    db.refresh(event)
    return event


@router.post(
    "/integrations/webhooks",
    response_model=IntegrationWebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_integration_webhook(
    request: IntegrationWebhookCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.integration.manage")),
) -> IntegrationWebhook:
    actor, tenant_id = identity
    try:
        target_host = validate_webhook_destination(request.target_url)[0]
    except WebhookConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    secret_exists = db.scalar(
        select(TenantSecret.id).where(
            TenantSecret.tenant_id == tenant_id,
            TenantSecret.name == request.secret_name,
        )
    )
    if secret_exists is None:
        raise HTTPException(
            status_code=422,
            detail="Webhook signing secret must exist in the tenant secret store",
        )
    webhook_count = db.scalar(
        select(func.count())
        .select_from(IntegrationWebhook)
        .where(IntegrationWebhook.tenant_id == tenant_id)
    )
    if webhook_count is not None and webhook_count >= 100:
        raise HTTPException(
            status_code=409,
            detail="Tenant webhook subscription limit reached",
        )

    webhook = IntegrationWebhook(
        tenant_id=tenant_id,
        name=request.name,
        target_url=request.target_url,
        secret_name=request.secret_name,
        event_types=request.event_types,
        status=request.status,
        created_by=actor,
    )
    try:
        db.add(webhook)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="WEBHOOK_SUBSCRIPTION_CREATED",
            resource_type="IntegrationWebhook",
            resource_id=webhook.id,
            outcome="SUCCESS",
            detail={
                "name": webhook.name,
                "target_host": target_host,
                "status": webhook.status.value,
                "event_type_count": len(webhook.event_types),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Webhook subscription name already exists",
        ) from exc
    db.refresh(webhook)
    return webhook


@router.get(
    "/integrations/webhooks",
    response_model=list[IntegrationWebhookResponse],
)
def list_integration_webhooks(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.integration.read")),
    webhook_status: IntegrationWebhookStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[IntegrationWebhook]:
    _actor, tenant_id = identity
    statement = select(IntegrationWebhook).where(
        IntegrationWebhook.tenant_id == tenant_id
    )
    if webhook_status is not None:
        statement = statement.where(IntegrationWebhook.status == webhook_status)
    return list(
        db.scalars(
            statement.order_by(IntegrationWebhook.name.asc())
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/integrations/webhooks/{webhook_id}",
    response_model=IntegrationWebhookResponse,
)
def get_integration_webhook(
    webhook_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.integration.read")),
) -> IntegrationWebhook:
    _actor, tenant_id = identity
    webhook = db.scalar(
        select(IntegrationWebhook).where(
            IntegrationWebhook.id == webhook_id,
            IntegrationWebhook.tenant_id == tenant_id,
        )
    )
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    return webhook


@router.patch(
    "/integrations/webhooks/{webhook_id}",
    response_model=IntegrationWebhookResponse,
)
def update_integration_webhook(
    webhook_id: str,
    request: IntegrationWebhookUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.integration.manage")),
) -> IntegrationWebhook:
    actor, tenant_id = identity
    webhook = db.scalar(
        select(IntegrationWebhook)
        .where(
            IntegrationWebhook.id == webhook_id,
            IntegrationWebhook.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")

    updates = request.model_dump(exclude_unset=True)
    target_url = updates.get("target_url", webhook.target_url)
    secret_name = updates.get("secret_name", webhook.secret_name)
    remains_enabled = (
        updates.get("status", webhook.status) == IntegrationWebhookStatus.ENABLED
    )
    target_host: str | None = None
    if "target_url" in updates or remains_enabled:
        try:
            target_host = validate_webhook_destination(target_url)[0]
        except WebhookConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "secret_name" in updates or remains_enabled:
        secret_exists = db.scalar(
            select(TenantSecret.id).where(
                TenantSecret.tenant_id == tenant_id,
                TenantSecret.name == secret_name,
            )
        )
        if secret_exists is None:
            raise HTTPException(
                status_code=422,
                detail="Webhook signing secret must exist in the tenant secret store",
            )

    for field, value in updates.items():
        setattr(webhook, field, value)
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="WEBHOOK_SUBSCRIPTION_UPDATED",
        resource_type="IntegrationWebhook",
        resource_id=webhook.id,
        outcome="SUCCESS",
        detail={
            "fields": sorted(updates),
            "target_host": target_host,
            "event_type_count": len(webhook.event_types),
            "status": webhook.status.value,
        },
    )
    db.commit()
    db.refresh(webhook)
    return webhook


@router.get(
    "/integrations/webhooks/{webhook_id}/deliveries",
    response_model=list[IntegrationWebhookDeliveryResponse],
)
def list_integration_webhook_deliveries(
    webhook_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.integration.read")),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[IntegrationWebhookDeliveryResponse]:
    _actor, tenant_id = identity
    webhook_exists = db.scalar(
        select(IntegrationWebhook.id).where(
            IntegrationWebhook.id == webhook_id,
            IntegrationWebhook.tenant_id == tenant_id,
        )
    )
    if webhook_exists is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    rows = db.execute(
        select(IntegrationWebhookDelivery, ControlTask, TaskWorkItem)
        .join(ControlTask, ControlTask.id == IntegrationWebhookDelivery.task_id)
        .join(TaskWorkItem, TaskWorkItem.task_id == ControlTask.id)
        .where(
            IntegrationWebhookDelivery.webhook_id == webhook_id,
            IntegrationWebhookDelivery.tenant_id == tenant_id,
        )
        .order_by(
            IntegrationWebhookDelivery.created_at.desc(),
            IntegrationWebhookDelivery.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return [
        IntegrationWebhookDeliveryResponse(
            id=delivery.id,
            webhook_id=delivery.webhook_id,
            event_id=delivery.event_id,
            task_id=task.id,
            status=task.status,
            attempts=work_item.attempts,
            failure_reason=task.failure_reason,
            created_at=delivery.created_at,
            finished_at=task.finished_at,
        )
        for delivery, task, work_item in rows
    ]


@router.get("/events", response_model=list[EventResponse])
def list_events(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.event.read")),
    event_type: str | None = Query(default=None, min_length=1, max_length=128),
    source_system_id: str | None = Query(default=None, min_length=36, max_length=36),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ControlEvent]:
    _actor, tenant_id = identity
    statement = select(ControlEvent).where(ControlEvent.tenant_id == tenant_id)
    if event_type is not None:
        statement = statement.where(ControlEvent.event_type == event_type)
    if source_system_id is not None:
        statement = statement.where(ControlEvent.source_system_id == source_system_id)
    statement = (
        statement.order_by(ControlEvent.created_at.desc()).offset(offset).limit(limit)
    )
    return list(db.scalars(statement))


@router.put("/config", response_model=ConfigurationResponse)
def upsert_configuration(
    request: ConfigurationUpsert,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.config.manage")),
) -> TenantConfiguration:
    actor, tenant_id = identity
    configuration = db.scalar(
        select(TenantConfiguration).where(
            TenantConfiguration.tenant_id == tenant_id,
            TenantConfiguration.key == request.key,
        )
    )
    action = "CONFIGURATION_UPDATED"
    if configuration is None:
        configuration = TenantConfiguration(
            tenant_id=tenant_id,
            key=request.key,
            value=request.value,
            created_by=actor,
            updated_by=actor,
        )
        action = "CONFIGURATION_CREATED"
    else:
        configuration.value = request.value
        configuration.updated_by = actor

    try:
        db.add(configuration)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type="TenantConfiguration",
            resource_id=configuration.id,
            outcome="SUCCESS",
            detail={"key": configuration.key},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Configuration changed concurrently; retry the request",
        ) from exc
    db.refresh(configuration)
    return configuration


@router.get("/config", response_model=list[ConfigurationResponse])
def list_configurations(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.config.read")),
) -> list[TenantConfiguration]:
    _actor, tenant_id = identity
    return list(
        db.scalars(
            select(TenantConfiguration)
            .where(TenantConfiguration.tenant_id == tenant_id)
            .order_by(TenantConfiguration.key.asc())
        )
    )


@router.get("/config/{configuration_id}", response_model=ConfigurationResponse)
def get_configuration(
    configuration_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.config.read")),
) -> TenantConfiguration:
    _actor, tenant_id = identity
    configuration = db.scalar(
        select(TenantConfiguration).where(
            TenantConfiguration.id == configuration_id,
            TenantConfiguration.tenant_id == tenant_id,
        )
    )
    if configuration is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return configuration


@router.delete("/config/{configuration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_configuration(
    configuration_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.config.manage")),
) -> None:
    actor, tenant_id = identity
    configuration = db.scalar(
        select(TenantConfiguration).where(
            TenantConfiguration.id == configuration_id,
            TenantConfiguration.tenant_id == tenant_id,
        )
    )
    if configuration is None:
        raise HTTPException(status_code=404, detail="Configuration not found")

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="CONFIGURATION_DELETED",
        resource_type="TenantConfiguration",
        resource_id=configuration.id,
        outcome="SUCCESS",
        detail={"key": configuration.key},
    )
    db.delete(configuration)
    db.commit()


@router.put("/secrets", response_model=SecretMetadataResponse)
def upsert_secret(
    request: SecretUpsert,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.secret.manage")),
) -> TenantSecret:
    actor, tenant_id = identity
    try:
        ciphertext = encrypt_secret(request.value.get_secret_value())
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    secret = db.scalar(
        select(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id,
            TenantSecret.name == request.name,
        )
    )
    action = "SECRET_UPDATED"
    if secret is None:
        secret = TenantSecret(
            tenant_id=tenant_id,
            name=request.name,
            ciphertext=ciphertext,
            created_by=actor,
            updated_by=actor,
        )
        action = "SECRET_CREATED"
    else:
        secret.ciphertext = ciphertext
        secret.updated_by = actor

    try:
        db.add(secret)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type="TenantSecret",
            resource_id=secret.id,
            outcome="SUCCESS",
            detail={"name": secret.name},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Secret changed concurrently; retry the request",
        ) from exc
    db.refresh(secret)
    return secret


@router.get("/secrets", response_model=list[SecretMetadataResponse])
def list_secrets(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.secret.read")),
) -> list[TenantSecret]:
    _actor, tenant_id = identity
    return list(
        db.scalars(
            select(TenantSecret)
            .where(TenantSecret.tenant_id == tenant_id)
            .order_by(TenantSecret.name.asc())
        )
    )


@router.delete("/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret(
    secret_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.secret.manage")),
) -> None:
    actor, tenant_id = identity
    secret = db.scalar(
        select(TenantSecret).where(
            TenantSecret.id == secret_id,
            TenantSecret.tenant_id == tenant_id,
        )
    )
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    active_webhook = db.scalar(
        select(IntegrationWebhook.id).where(
            IntegrationWebhook.tenant_id == tenant_id,
            IntegrationWebhook.secret_name == secret.name,
            IntegrationWebhook.status == IntegrationWebhookStatus.ENABLED,
        )
    )
    if active_webhook is not None:
        raise HTTPException(
            status_code=409,
            detail="Disable webhook subscriptions before deleting their signing secret",
        )

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="SECRET_DELETED",
        resource_type="TenantSecret",
        resource_id=secret.id,
        outcome="SUCCESS",
        detail={"name": secret.name},
    )
    db.delete(secret)
    db.commit()


@router.post("/commands", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
def create_command(
    request: CommandCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.create")),
) -> Command:
    actor, tenant_id = identity
    stop = emergency_stop(db, tenant_id)
    if stop.active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    policy = db.scalar(
        select(CommandPolicy).where(
            CommandPolicy.tenant_id == tenant_id,
            CommandPolicy.command_type == request.type,
            CommandPolicy.enabled.is_(True),
        )
    )
    approval_payload_rule_matched = False
    policy_snapshot = None
    policy_version = None
    if policy is not None:
        approval_payload_keys = list(
            db.scalars(
                select(CommandPolicyPayloadRule.payload_key).where(
                    CommandPolicyPayloadRule.policy_id == policy.id
                )
            )
        )
        approval_payload_rule_matched = any(
            _payload_has_path(request.payload, payload_key)
            for payload_key in approval_payload_keys
        )
        latest_version = _latest_policy_version(db, policy.id)
        policy_version = latest_version.version if latest_version is not None else 1
        policy_snapshot = _policy_snapshot(policy, approval_payload_keys)
    require_approval = (
        request.require_approval
        or policy is None
        or policy.require_approval
        or approval_payload_rule_matched
    )
    require_different_approver = (
        policy.require_different_approver if policy is not None else True
    )
    command = Command(
        tenant_id=tenant_id,
        type=request.type,
        payload=request.payload,
        status=(
            CommandStatus.RECEIVED
            if require_approval
            else CommandStatus.APPROVED
        ),
        created_by=actor,
    )
    db.add(command)
    db.flush()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="COMMAND_CREATED",
        resource_type="Command",
        resource_id=command.id,
        outcome="SUCCESS",
        detail={
            "type": command.type,
            "require_approval": require_approval,
            "require_different_approver": require_different_approver,
            "policy_id": policy.id if policy is not None else None,
            "policy_version": policy_version,
            "policy_snapshot": policy_snapshot,
            "approval_payload_rule_matched": approval_payload_rule_matched,
        },
    )
    db.commit()
    db.refresh(command)
    return command


@router.get("/commands", response_model=list[CommandResponse])
def list_commands(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.read")),
    status_filter: CommandStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Command]:
    _actor, tenant_id = identity
    statement = select(Command).where(Command.tenant_id == tenant_id)
    if status_filter is not None:
        statement = statement.where(Command.status == status_filter)
    statement = statement.order_by(Command.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(statement))


@router.get("/commands/{command_id}", response_model=CommandResponse)
def get_command(
    command_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.read")),
) -> Command:
    actor, tenant_id = identity
    command = db.scalar(
        select(Command).where(Command.id == command_id, Command.tenant_id == tenant_id)
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return command


@router.post("/commands/{command_id}/approve", response_model=CommandResponse)
def approve_command(
    command_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.approve")),
) -> Command:
    actor, tenant_id = identity
    stop = emergency_stop(db, tenant_id)
    if stop.active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    command = db.scalar(
        select(Command)
        .where(Command.id == command_id, Command.tenant_id == tenant_id)
        .with_for_update()
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status != CommandStatus.RECEIVED:
        raise HTTPException(status_code=409, detail=f"Command cannot be approved from {command.status.value}")

    creation_event = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "COMMAND_CREATED",
            AuditEvent.resource_id == command.id,
        )
        .order_by(AuditEvent.created_at.asc())
        .limit(1)
    )
    require_different_approver = bool(
        creation_event
        and creation_event.detail.get("require_different_approver", False)
    )
    if require_different_approver and command.created_by == actor:
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="COMMAND_APPROVAL_REJECTED",
            resource_type="Command",
            resource_id=command.id,
            outcome="DENIED",
            detail={"reason": "Creator cannot approve this command"},
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="Command creator cannot approve this command",
        )

    command.status = CommandStatus.APPROVED
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="COMMAND_APPROVED",
        resource_type="Command",
        resource_id=command.id,
        outcome="SUCCESS",
        detail={},
    )
    db.commit()
    db.refresh(command)
    return command


@router.post("/commands/{command_id}/execute", response_model=CommandResponse)
def execute_command(
    command_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.execute")),
) -> Command:
    actor, tenant_id = identity
    stop = emergency_stop(db, tenant_id)
    if stop.active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    command = db.scalar(
        select(Command)
        .where(Command.id == command_id, Command.tenant_id == tenant_id)
        .with_for_update()
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status != CommandStatus.APPROVED:
        raise HTTPException(status_code=409, detail=f"Command cannot execute from {command.status.value}")

    command.status = CommandStatus.COMPLETED
    command.result = "Executed successfully"
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="COMMAND_EXECUTED",
        resource_type="Command",
        resource_id=command.id,
        outcome="SUCCESS",
        detail={"result": command.result},
    )
    db.commit()
    db.refresh(command)
    return command


@router.post("/commands/{command_id}/cancel", response_model=CommandResponse)
def cancel_command(
    command_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.cancel")),
) -> Command:
    actor, tenant_id = identity
    command = db.scalar(
        select(Command).where(Command.id == command_id, Command.tenant_id == tenant_id)
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status in {CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail=f"Command cannot cancel from {command.status.value}")

    command.status = CommandStatus.CANCELLED
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="COMMAND_CANCELLED",
        resource_type="Command",
        resource_id=command.id,
        outcome="SUCCESS",
        detail={},
    )
    db.commit()
    db.refresh(command)
    return command


@router.get("/audit", response_model=list[AuditResponse])
def list_audit(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.audit.read")),
) -> list[AuditEvent]:
    _actor, tenant_id = identity
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(100)
        )
    )


@router.post("/emergency-stop", response_model=EmergencyStopResponse)
def activate_emergency_stop(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.emergency.stop")),
) -> EmergencyStop:
    actor, tenant_id = identity
    stop = emergency_stop(db, tenant_id)
    stop.active = True
    stop.activated_by = actor
    stop.activated_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="EMERGENCY_STOP_ACTIVATED",
        resource_type="EmergencyStop",
        resource_id=None,
        outcome="SUCCESS",
        detail={},
    )
    db.commit()
    db.refresh(stop)
    return stop


@router.delete("/emergency-stop", response_model=EmergencyStopResponse)
def clear_emergency_stop(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.emergency.clear")),
) -> EmergencyStop:
    actor, tenant_id = identity
    stop = emergency_stop(db, tenant_id)
    stop.active = False
    stop.activated_by = None
    stop.activated_at = None
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="EMERGENCY_STOP_CLEARED",
        resource_type="EmergencyStop",
        resource_id=None,
        outcome="SUCCESS",
        detail={},
    )
    db.commit()
    db.refresh(stop)
    return stop


@router.post("/models", response_model=AIModelResponse, status_code=status.HTTP_201_CREATED)
def create_model(
    request: AIModelCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.create")),
) -> AIModel:
    actor, tenant_id = identity
    existing = db.scalar(
        select(AIModel).where(
            AIModel.tenant_id == tenant_id,
            AIModel.name == request.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Model name already exists")

    model = AIModel(
        tenant_id=tenant_id,
        name=request.name,
        provider=request.provider,
        model_identifier=request.model_identifier,
        capabilities=request.capabilities,
        status=request.status,
        priority=request.priority,
    )
    db.add(model)
    db.flush()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="MODEL_CREATED",
        resource_type="AIModel",
        resource_id=model.id,
        outcome="SUCCESS",
        detail={
            "name": model.name,
            "provider": model.provider,
            "status": model.status.value,
        },
    )
    db.commit()
    db.refresh(model)
    return model


@router.get("/models", response_model=list[AIModelResponse])
def list_models(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.read")),
) -> list[AIModel]:
    _actor, tenant_id = identity
    return list(
        db.scalars(
            select(AIModel)
            .where(AIModel.tenant_id == tenant_id)
            .order_by(AIModel.priority.desc(), AIModel.name.asc())
        )
    )


@router.get("/models/{model_id}", response_model=AIModelResponse)
def get_model(
    model_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.read")),
) -> AIModel:
    _actor, tenant_id = identity
    model = db.scalar(
        select(AIModel).where(AIModel.id == model_id, AIModel.tenant_id == tenant_id)
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.patch("/models/{model_id}", response_model=AIModelResponse)
def update_model(
    model_id: str,
    request: AIModelUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.update")),
) -> AIModel:
    actor, tenant_id = identity
    model = db.scalar(
        select(AIModel).where(AIModel.id == model_id, AIModel.tenant_id == tenant_id)
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(model, field, value)

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="MODEL_UPDATED",
        resource_type="AIModel",
        resource_id=model.id,
        outcome="SUCCESS",
        detail={"fields": sorted(updates)},
    )
    db.commit()
    db.refresh(model)
    return model


@router.post("/models/route", response_model=ModelRouteResponse)
def route_model(
    request: ModelRouteRequest,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.route")),
) -> ModelRouteResponse:
    _actor, tenant_id = identity
    statement = (
        select(AIModel)
        .where(
            AIModel.tenant_id == tenant_id,
            AIModel.status == AIModelStatus.ENABLED,
        )
        .order_by(AIModel.priority.desc(), AIModel.name.asc())
    )
    if request.provider is not None:
        statement = statement.where(AIModel.provider == request.provider)

    candidates = list(db.scalars(statement))
    model = next(
        (candidate for candidate in candidates if request.capability in candidate.capabilities),
        None,
    )
    if model is None:
        raise HTTPException(status_code=404, detail="No enabled model matches the request")

    return ModelRouteResponse(
        model_id=model.id,
        name=model.name,
        provider=model.provider,
        model_identifier=model.model_identifier,
    )


def get_inference_provider() -> InferenceProvider:
    return OpenAICompatibleProvider(settings)


@router.get(
    "/models/catalog/discover",
    response_model=AIModelDiscoveryResponse,
)
def discover_models(
    provider_name: str = Query(default="openai-compatible", min_length=1, max_length=128),
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.route")),
    provider: InferenceProvider = Depends(get_inference_provider),
) -> AIModelDiscoveryResponse:
    actor, tenant_id = identity
    if provider_name != provider.provider_name:
        raise HTTPException(
            status_code=501,
            detail=f"Provider {provider_name} is not supported for discovery",
        )
    try:
        identifiers = provider.discover_models()
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (ProviderRequestError, ProviderResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="MODEL_DISCOVERY_COMPLETED",
        resource_type="AIModel",
        resource_id=None,
        outcome="SUCCESS",
        detail={
            "provider": provider_name,
            "model_count": len(identifiers),
        },
    )
    db.commit()
    return AIModelDiscoveryResponse(
        provider=provider_name,
        model_identifiers=identifiers,
    )


@router.post(
    "/models/{model_id}/health",
    response_model=AIModelHealthResponse,
)
def check_model_health(
    model_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.model.update")),
    provider: InferenceProvider = Depends(get_inference_provider),
) -> AIModelHealthResponse:
    actor, tenant_id = identity
    model = db.scalar(
        select(AIModel)
        .where(AIModel.id == model_id, AIModel.tenant_id == tenant_id)
        .with_for_update()
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.provider != provider.provider_name:
        raise HTTPException(
            status_code=501,
            detail=f"Provider {model.provider} is not supported for health checks",
        )

    checked_at = utcnow()
    try:
        identifiers = provider.discover_models()
        if model.model_identifier in identifiers:
            model.health_status = AIModelHealthStatus.HEALTHY
            model.health_error = None
            outcome = "SUCCESS"
            action = "MODEL_HEALTH_CHECK_COMPLETED"
        else:
            model.health_status = AIModelHealthStatus.UNHEALTHY
            model.health_error = "Model identifier is not present in the provider catalog"
            outcome = "FAILED"
            action = "MODEL_HEALTH_CHECK_COMPLETED"
    except (ProviderNotConfiguredError, ProviderTimeoutError, ProviderRequestError, ProviderResponseError) as exc:
        model.health_status = AIModelHealthStatus.UNHEALTHY
        model.health_error = str(exc)[:2000]
        outcome = "FAILED"
        action = "MODEL_HEALTH_CHECK_COMPLETED"

    model.last_health_check_at = checked_at
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        resource_type="AIModel",
        resource_id=model.id,
        outcome=outcome,
        detail={
            "health_status": model.health_status.value,
            "provider": model.provider,
        },
    )
    db.commit()
    db.refresh(model)
    return model


def _run_inference(
    request: InferenceRequest,
    db: Session,
    identity: tuple[str, str],
    provider: InferenceProvider,
) -> InferenceResponse:
    actor, tenant_id = identity
    new_conversation_messages = list(request.messages)
    stop = emergency_stop(db, tenant_id)
    if stop.active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    if request.conversation_id is not None:
        conversation = db.scalar(
            select(AIConversation).where(
                AIConversation.id == request.conversation_id,
                AIConversation.tenant_id == tenant_id,
                AIConversation.created_by == actor,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        new_messages = list(request.messages)
        stored = list(
            db.scalars(
                select(AIConversationMessage)
                .where(AIConversationMessage.conversation_id == conversation.id)
                .order_by(AIConversationMessage.sequence.asc())
                .limit(100)
            )
        )
        stored_messages = [
            AIMessage(role=message.role, content=message.content)
            for message in stored
            if message.role in {"system", "user", "assistant"}
        ]
        request.messages = (
            [message for message in new_messages if message.role == "system"]
            + stored_messages
            + [message for message in new_messages if message.role != "system"]
        )
        request.conversation_id = conversation.id

    statement = (
        select(AIModel)
        .where(
            AIModel.tenant_id == tenant_id,
            AIModel.status == AIModelStatus.ENABLED,
        )
        .order_by(AIModel.priority.desc(), AIModel.name.asc())
    )
    if request.provider is not None:
        statement = statement.where(AIModel.provider == request.provider)
    candidates = list(db.scalars(statement))
    model = next(
        (candidate for candidate in candidates if "chat" in candidate.capabilities),
        None,
    )
    if model is None:
        raise HTTPException(status_code=404, detail="No enabled chat model is registered")
    if model.provider != provider.provider_name:
        raise HTTPException(
            status_code=501,
            detail=f"Provider {model.provider} is not supported for inference",
        )

    try:
        result = provider.generate(
            model_identifier=model.model_identifier,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=request.response_format,
            tools=request.tools,
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (ProviderRequestError, ProviderResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except UnsupportedProviderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="AI_INFERENCE_COMPLETED",
        resource_type="AIModel",
        resource_id=model.id,
        outcome="SUCCESS",
        detail={
            "capability": "chat",
            "provider": model.provider,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    )
    conversation_id = request.conversation_id
    if conversation_id is not None:
        conversation = db.scalar(
            select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.tenant_id == tenant_id,
                AIConversation.created_by == actor,
            )
        )
        if conversation is not None:
            sequences = list(
                db.scalars(
                    select(AIConversationMessage.sequence)
                    .where(AIConversationMessage.conversation_id == conversation.id)
                    .order_by(AIConversationMessage.sequence.desc())
                    .limit(1)
                )
            )
            next_sequence = (sequences[0] + 1) if sequences else 1
            request_messages = new_conversation_messages
            db.add_all(
                AIConversationMessage(
                    conversation_id=conversation.id,
                    tenant_id=tenant_id,
                    sequence=next_sequence + offset,
                    role=message.role,
                    content=message.content,
                )
                for offset, message in enumerate(request_messages)
                if message.role in {"user", "assistant"}
            )
            db.add(
                AIConversationMessage(
                    conversation_id=conversation.id,
                    tenant_id=tenant_id,
                    sequence=next_sequence + len(request_messages),
                    role="assistant",
                    content=result.content,
                )
            )
            conversation.updated_at = utcnow()
    db.commit()
    return InferenceResponse(
        model_id=model.id,
        model_name=model.name,
        provider=model.provider,
        model_identifier=model.model_identifier,
        content=result.content,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        conversation_id=conversation_id,
        tool_calls=result.tool_calls or [],
        structured_output=result.structured_output,
    )


@router.post("/nexus/chat", response_model=InferenceResponse)
def nexus_chat(
    request: NexusChatRequest,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.ai.infer")),
    provider: InferenceProvider = Depends(get_inference_provider),
) -> InferenceResponse:
    inference_request = InferenceRequest(
        messages=build_nexus_messages(request.messages),
        provider=request.provider,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    return _run_inference(inference_request, db, identity, provider)


@router.post(
    "/ai/conversations",
    response_model=AIConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ai_conversation(
    request: AIConversationCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.ai.infer")),
) -> AIConversation:
    actor, tenant_id = identity
    conversation = AIConversation(
        tenant_id=tenant_id,
        created_by=actor,
        title=request.title,
    )
    db.add(conversation)
    db.flush()
    conversation_id = conversation.id
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="AI_CONVERSATION_CREATED",
        resource_type="AIConversation",
        resource_id=conversation_id,
        outcome="SUCCESS",
        detail={"title": request.title},
    )
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get(
    "/ai/conversations/{conversation_id}/messages",
    response_model=list[AIConversationMessageResponse],
)
def list_ai_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.ai.infer")),
) -> list[AIConversationMessage]:
    actor, tenant_id = identity
    conversation = db.scalar(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.tenant_id == tenant_id,
            AIConversation.created_by == actor,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        db.scalars(
            select(AIConversationMessage)
            .where(AIConversationMessage.conversation_id == conversation.id)
            .order_by(AIConversationMessage.sequence.asc())
        )
    )


@router.delete(
    "/ai/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_ai_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.ai.infer")),
) -> None:
    actor, tenant_id = identity
    conversation = db.scalar(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.tenant_id == tenant_id,
            AIConversation.created_by == actor,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.execute(
        delete(AIConversationMessage).where(
            AIConversationMessage.conversation_id == conversation.id
        )
    )
    db.delete(conversation)
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="AI_CONVERSATION_DELETED",
        resource_type="AIConversation",
        resource_id=conversation.id,
        outcome="SUCCESS",
        detail={},
    )
    db.commit()


KNOWLEDGE_CHUNK_SIZE = 1200
KNOWLEDGE_CHUNK_OVERLAP = 200


def _knowledge_chunks(content: str) -> list[tuple[int, int, str]]:
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + KNOWLEDGE_CHUNK_SIZE, len(content))
        chunks.append((start, end, content[start:end]))
        if end == len(content):
            break
        start = end - KNOWLEDGE_CHUNK_OVERLAP
    return chunks


def _store_knowledge_version(
    db: Session,
    *,
    document: KnowledgeDocument,
    content: str,
    actor: str,
) -> None:
    version = KnowledgeDocumentVersion(
        document_id=document.id,
        tenant_id=document.tenant_id,
        version=document.current_version,
        content=content,
        created_by=actor,
    )
    db.add(version)
    db.flush()
    db.add_all(
        KnowledgeChunk(
            document_id=document.id,
            document_version_id=version.id,
            tenant_id=document.tenant_id,
            chunk_index=index,
            start_offset=start,
            end_offset=end,
            content=chunk,
        )
        for index, (start, end, chunk) in enumerate(_knowledge_chunks(content))
    )


def _knowledge_document_for_tenant(
    db: Session,
    *,
    document_id: str,
    tenant_id: str,
) -> KnowledgeDocument:
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == tenant_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return document


def _knowledge_source_for_tenant(
    db: Session,
    *,
    source_id: str,
    tenant_id: str,
) -> KnowledgeSource:
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == tenant_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return source


@router.post(
    "/knowledge/sources",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_source(
    request: KnowledgeSourceCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.manage")),
) -> KnowledgeSource:
    actor, tenant_id = identity
    existing = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.name == request.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Knowledge source name already exists")
    source = KnowledgeSource(
        tenant_id=tenant_id,
        created_by=actor,
        last_verified_at=utcnow() if request.status == KnowledgeSourceStatus.VERIFIED else None,
        **request.model_dump(exclude={"status"}),
        status=request.status,
    )
    try:
        db.add(source)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="KNOWLEDGE_SOURCE_CREATED",
            resource_type="KnowledgeSource",
            resource_id=source.id,
            outcome="SUCCESS",
            detail={
                "name": source.name,
                "source_type": source.source_type,
                "credibility": source.credibility.value,
                "status": source.status.value,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Knowledge source name already exists",
        ) from exc
    db.refresh(source)
    return source


@router.get(
    "/knowledge/sources",
    response_model=list[KnowledgeSourceResponse],
)
def list_knowledge_sources(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
    source_status: KnowledgeSourceStatus | None = Query(default=None, alias="status"),
    credibility: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeSource]:
    _actor, tenant_id = identity
    statement = select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)
    if source_status is not None:
        statement = statement.where(KnowledgeSource.status == source_status)
    if credibility is not None:
        from app.models import KnowledgeSourceCredibility

        try:
            credibility_level = KnowledgeSourceCredibility(credibility.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid credibility level") from exc
        statement = statement.where(KnowledgeSource.credibility == credibility_level)
    return list(
        db.scalars(
            statement.order_by(KnowledgeSource.name.asc())
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/knowledge/sources/{source_id}",
    response_model=KnowledgeSourceResponse,
)
def get_knowledge_source(
    source_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
) -> KnowledgeSource:
    _actor, tenant_id = identity
    return _knowledge_source_for_tenant(db, source_id=source_id, tenant_id=tenant_id)


@router.patch(
    "/knowledge/sources/{source_id}",
    response_model=KnowledgeSourceResponse,
)
def update_knowledge_source(
    source_id: str,
    request: KnowledgeSourceUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.manage")),
) -> KnowledgeSource:
    actor, tenant_id = identity
    source = db.scalar(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")

    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(source, field, value)
    if "status" in updates and source.status == KnowledgeSourceStatus.VERIFIED:
        source.last_verified_at = utcnow()
    source.updated_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="KNOWLEDGE_SOURCE_UPDATED",
        resource_type="KnowledgeSource",
        resource_id=source.id,
        outcome="SUCCESS",
        detail={"fields": sorted(updates)},
    )
    db.commit()
    db.refresh(source)
    return source


@router.delete(
    "/knowledge/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_knowledge_source(
    source_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.manage")),
) -> None:
    actor, tenant_id = identity
    source = _knowledge_source_for_tenant(db, source_id=source_id, tenant_id=tenant_id)
    db.delete(source)
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="KNOWLEDGE_SOURCE_DELETED",
        resource_type="KnowledgeSource",
        resource_id=source.id,
        outcome="SUCCESS",
        detail={"name": source.name},
    )
    db.commit()


@router.post(
    "/knowledge/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_document(
    request: KnowledgeDocumentCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.manage")),
) -> KnowledgeDocument:
    actor, tenant_id = identity
    existing = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.name == request.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Knowledge document name already exists")

    document = KnowledgeDocument(
        tenant_id=tenant_id,
        name=request.name,
        description=request.description,
        source=request.source,
        status=request.status,
        current_version=1,
        created_by=actor,
    )
    try:
        db.add(document)
        db.flush()
        _store_knowledge_version(
            db,
            document=document,
            content=request.content,
            actor=actor,
        )
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="KNOWLEDGE_DOCUMENT_CREATED",
            resource_type="KnowledgeDocument",
            resource_id=document.id,
            outcome="SUCCESS",
            detail={
                "name": document.name,
                "status": document.status.value,
                "version": document.current_version,
                "chunk_count": len(_knowledge_chunks(request.content)),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Knowledge document name already exists",
        ) from exc
    db.refresh(document)
    return document


@router.get(
    "/knowledge/documents",
    response_model=list[KnowledgeDocumentResponse],
)
def list_knowledge_documents(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
    document_status: KnowledgeDocumentStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeDocument]:
    _actor, tenant_id = identity
    statement = select(KnowledgeDocument).where(
        KnowledgeDocument.tenant_id == tenant_id
    )
    if document_status is not None:
        statement = statement.where(KnowledgeDocument.status == document_status)
    return list(
        db.scalars(
            statement.order_by(KnowledgeDocument.name.asc())
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/knowledge/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
)
def get_knowledge_document(
    document_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
) -> KnowledgeDocument:
    _actor, tenant_id = identity
    return _knowledge_document_for_tenant(
        db,
        document_id=document_id,
        tenant_id=tenant_id,
    )


@router.get(
    "/knowledge/documents/{document_id}/content",
    response_model=KnowledgeDocumentContentResponse,
)
def get_knowledge_document_content(
    document_id: str,
    version_number: int | None = Query(default=None, ge=1, alias="version"),
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
) -> KnowledgeDocumentContentResponse:
    _actor, tenant_id = identity
    document = _knowledge_document_for_tenant(
        db,
        document_id=document_id,
        tenant_id=tenant_id,
    )
    version = db.scalar(
        select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document.id,
            KnowledgeDocumentVersion.tenant_id == tenant_id,
            KnowledgeDocumentVersion.version
            == (version_number or document.current_version),
        )
    )
    if version is None:
        raise HTTPException(status_code=500, detail="Current knowledge version is missing")
    return KnowledgeDocumentContentResponse(
        document=KnowledgeDocumentResponse.model_validate(document),
        version=version.version,
        content=version.content,
    )


@router.get(
    "/knowledge/documents/{document_id}/versions",
    response_model=list[KnowledgeDocumentVersionResponse],
)
def list_knowledge_document_versions(
    document_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
) -> list[KnowledgeDocumentVersion]:
    _actor, tenant_id = identity
    document = _knowledge_document_for_tenant(
        db,
        document_id=document_id,
        tenant_id=tenant_id,
    )
    return list(
        db.scalars(
            select(KnowledgeDocumentVersion)
            .where(
                KnowledgeDocumentVersion.document_id == document.id,
                KnowledgeDocumentVersion.tenant_id == tenant_id,
            )
            .order_by(KnowledgeDocumentVersion.version.asc())
        )
    )


@router.patch(
    "/knowledge/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
)
def update_knowledge_document(
    document_id: str,
    request: KnowledgeDocumentUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.manage")),
) -> KnowledgeDocument:
    actor, tenant_id = identity
    document = db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    updates = request.model_dump(exclude_unset=True)
    content = updates.pop("content", None)
    for field, value in updates.items():
        setattr(document, field, value)
    if content is not None:
        document.current_version += 1
        _store_knowledge_version(
            db,
            document=document,
            content=content,
            actor=actor,
        )
    document.updated_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="KNOWLEDGE_DOCUMENT_UPDATED",
        resource_type="KnowledgeDocument",
        resource_id=document.id,
        outcome="SUCCESS",
        detail={
            "fields": sorted(request.model_dump(exclude_unset=True)),
            "version": document.current_version,
        },
    )
    db.commit()
    db.refresh(document)
    return document


@router.delete(
    "/knowledge/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_knowledge_document(
    document_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.manage")),
) -> None:
    actor, tenant_id = identity
    document = _knowledge_document_for_tenant(
        db,
        document_id=document_id,
        tenant_id=tenant_id,
    )
    db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
    )
    db.execute(
        delete(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document.id
        )
    )
    db.delete(document)
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="KNOWLEDGE_DOCUMENT_DELETED",
        resource_type="KnowledgeDocument",
        resource_id=document.id,
        outcome="SUCCESS",
        detail={"name": document.name},
    )
    db.commit()


@router.post(
    "/knowledge/search",
    response_model=KnowledgeSearchResponse,
)
def search_knowledge(
    request: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.knowledge.read")),
) -> KnowledgeSearchResponse:
    actor, tenant_id = identity
    terms = list(dict.fromkeys(re.findall(r"\w+", request.query.lower())))
    term_matches = [
        func.lower(KnowledgeChunk.content).contains(term, autoescape=True)
        for term in terms
    ]
    matched_term_count = sum(case((match, 1), else_=0) for match in term_matches)
    statement = (
        select(
            KnowledgeChunk,
            KnowledgeDocumentVersion,
            KnowledgeDocument,
            matched_term_count.label("matched_term_count"),
        )
        .join(
            KnowledgeDocumentVersion,
            KnowledgeDocumentVersion.id == KnowledgeChunk.document_version_id,
        )
        .join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        )
        .where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeDocumentVersion.tenant_id == tenant_id,
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocumentVersion.version == KnowledgeDocument.current_version,
            KnowledgeDocument.status == KnowledgeDocumentStatus.ACTIVE,
            or_(*term_matches),
        )
    )
    if request.document_ids is not None:
        statement = statement.where(
            KnowledgeDocument.id.in_(request.document_ids)
        )
    rows = db.execute(
        statement.order_by(
            matched_term_count.desc(),
            KnowledgeDocument.name.asc(),
            KnowledgeChunk.chunk_index.asc(),
        ).limit(request.limit)
    ).all()
    hits = [
        KnowledgeSearchHit(
            document_id=document.id,
            document_name=document.name,
            source=document.source,
            version=version.version,
            chunk_index=chunk.chunk_index,
            text=chunk.content,
            score=matched_count / len(terms),
        )
        for chunk, version, document, matched_count in rows
    ]
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="KNOWLEDGE_SEARCH_COMPLETED",
        resource_type="KnowledgeDocument",
        resource_id=None,
        outcome="SUCCESS",
        detail={"hit_count": len(hits)},
    )
    db.commit()
    return KnowledgeSearchResponse(query=request.query, hits=hits)


@router.post(
    "/intelligence/assessments",
    response_model=DecisionAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_intelligence_assessment(
    request: DecisionAssessmentCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.intelligence.analyze")),
) -> DecisionAssessmentResponse:
    actor, tenant_id = identity
    assessment = IntelligenceAssessment(
        tenant_id=tenant_id,
        title=request.title,
        objective=request.objective,
        input_snapshot=request.model_dump(mode="json"),
        result_snapshot={},
        created_by=actor,
    )
    db.add(assessment)
    db.flush()
    result = analyze_decision(
        request,
        assessment_id=assessment.id,
        actor=actor,
        created_at=assessment.created_at,
    )
    assessment.result_snapshot = result.model_dump(mode="json")
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="INTELLIGENCE_ASSESSMENT_CREATED",
        resource_type="IntelligenceAssessment",
        resource_id=assessment.id,
        outcome="SUCCESS",
        detail={
            "criterion_count": len(request.criteria),
            "alternative_count": len(request.alternatives),
            "method": "WEIGHTED_SCORE_WITH_SEPARATE_RISK_MATRIX",
        },
    )
    db.commit()
    return result


@router.get(
    "/intelligence/assessments",
    response_model=list[DecisionAssessmentListItem],
)
def list_intelligence_assessments(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.intelligence.read")),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[DecisionAssessmentListItem]:
    _actor, tenant_id = identity
    assessments = db.scalars(
        select(IntelligenceAssessment)
        .where(IntelligenceAssessment.tenant_id == tenant_id)
        .order_by(
            IntelligenceAssessment.created_at.desc(),
            IntelligenceAssessment.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return [
        DecisionAssessmentListItem(
            id=assessment.id,
            title=assessment.title,
            created_by=assessment.created_by,
            created_at=assessment.created_at,
            criterion_count=len(assessment.input_snapshot["criteria"]),
            alternative_count=len(assessment.input_snapshot["alternatives"]),
        )
        for assessment in assessments
    ]


@router.get(
    "/intelligence/assessments/{assessment_id}",
    response_model=DecisionAssessmentResponse,
)
def get_intelligence_assessment(
    assessment_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.intelligence.read")),
) -> DecisionAssessmentResponse:
    _actor, tenant_id = identity
    assessment = db.scalar(
        select(IntelligenceAssessment).where(
            IntelligenceAssessment.id == assessment_id,
            IntelligenceAssessment.tenant_id == tenant_id,
        )
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="Intelligence assessment not found")
    return DecisionAssessmentResponse.model_validate(assessment.result_snapshot)


def automation_workflow_run_response(
    run: AutomationWorkflowRun,
) -> AutomationWorkflowRunResponse:
    return AutomationWorkflowRunResponse(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        task_id=run.task_id,
        status=run.status,
        input=run.input,
        step_results=run.step_results,
        result=run.result_snapshot,
        failure_reason=run.failure_reason,
        scheduled_at=run.scheduled_at,
        created_by=run.created_by,
        created_at=run.created_at,
    )


@router.post(
    "/workflows",
    response_model=AutomationWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_automation_workflow(
    request: AutomationWorkflowCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.manage")),
) -> AutomationWorkflow:
    actor, tenant_id = identity
    existing = db.scalar(
        select(AutomationWorkflow).where(
            AutomationWorkflow.tenant_id == tenant_id,
            AutomationWorkflow.name == request.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Workflow name already exists")
    workflow = AutomationWorkflow(
        tenant_id=tenant_id,
        name=request.name,
        description=request.description,
        steps=[step.model_dump(mode="json") for step in request.steps],
        version=1,
        status=request.status,
        created_by=actor,
    )
    try:
        db.add(workflow)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="WORKFLOW_CREATED",
            resource_type="AutomationWorkflow",
            resource_id=workflow.id,
            outcome="SUCCESS",
            detail={
                "name": workflow.name,
                "status": workflow.status.value,
                "version": workflow.version,
                "step_count": len(workflow.steps),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Workflow name already exists") from exc
    db.refresh(workflow)
    return workflow


@router.get(
    "/workflows",
    response_model=list[AutomationWorkflowResponse],
)
def list_automation_workflows(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.read")),
    workflow_status: AutomationWorkflowStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AutomationWorkflow]:
    _actor, tenant_id = identity
    statement = select(AutomationWorkflow).where(
        AutomationWorkflow.tenant_id == tenant_id
    )
    if workflow_status is not None:
        statement = statement.where(AutomationWorkflow.status == workflow_status)
    return list(
        db.scalars(
            statement.order_by(AutomationWorkflow.name.asc())
            .offset(offset)
            .limit(limit)
        )
    )


@router.get(
    "/workflows/{workflow_id}",
    response_model=AutomationWorkflowResponse,
)
def get_automation_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.read")),
) -> AutomationWorkflow:
    _actor, tenant_id = identity
    workflow = db.scalar(
        select(AutomationWorkflow).where(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.tenant_id == tenant_id,
        )
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.patch(
    "/workflows/{workflow_id}",
    response_model=AutomationWorkflowResponse,
)
def update_automation_workflow(
    workflow_id: str,
    request: AutomationWorkflowUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.manage")),
) -> AutomationWorkflow:
    actor, tenant_id = identity
    workflow = db.scalar(
        select(AutomationWorkflow)
        .where(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    updates = request.model_dump(exclude_unset=True)
    if "steps" in updates:
        new_steps = [step.model_dump(mode="json") for step in request.steps or []]
        if new_steps != workflow.steps:
            workflow.version += 1
        updates["steps"] = new_steps
    for field, value in updates.items():
        setattr(workflow, field, value)
    workflow.updated_at = utcnow()
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="WORKFLOW_UPDATED",
        resource_type="AutomationWorkflow",
        resource_id=workflow.id,
        outcome="SUCCESS",
        detail={
            "fields": sorted(updates),
            "version": workflow.version,
        },
    )
    db.commit()
    db.refresh(workflow)
    return workflow


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=AutomationWorkflowRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_automation_workflow_run(
    workflow_id: str,
    request: AutomationWorkflowRunCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.run")),
) -> AutomationWorkflowRunResponse:
    actor, tenant_id = identity
    workflow = db.scalar(
        select(AutomationWorkflow).where(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.tenant_id == tenant_id,
        )
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.status != AutomationWorkflowStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Workflow is not active")
    if emergency_stop(db, tenant_id).active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

    scheduled_at = utcnow() + timedelta(seconds=request.delay_seconds)
    task = ControlTask(
        tenant_id=tenant_id,
        title=f"Workflow: {workflow.name}",
        description=f"Workflow run version {workflow.version}",
        status=TaskStatus.PENDING,
        created_by=actor,
    )
    db.add(task)
    db.flush()
    run = AutomationWorkflowRun(
        task_id=task.id,
        workflow_id=workflow.id,
        tenant_id=tenant_id,
        workflow_version=workflow.version,
        input=request.input,
        steps_snapshot=workflow.steps,
        step_results=[],
        status=AutomationWorkflowRunStatus.QUEUED,
        scheduled_at=scheduled_at,
        created_by=actor,
    )
    db.add(run)
    db.flush()
    db.add(
        TaskWorkItem(
            task_id=task.id,
            tenant_id=tenant_id,
            work_type="automation.workflow",
            payload={"workflow_run_id": run.id},
            status=WorkItemStatus.PENDING,
            available_at=scheduled_at,
        )
    )
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="WORKFLOW_RUN_QUEUED",
        resource_type="AutomationWorkflowRun",
        resource_id=run.id,
        outcome="SUCCESS",
        detail={
            "workflow_id": workflow.id,
            "workflow_version": workflow.version,
            "delay_seconds": request.delay_seconds,
            "step_count": len(workflow.steps),
        },
    )
    db.commit()
    db.refresh(run)
    return automation_workflow_run_response(run)


@router.get(
    "/workflows/{workflow_id}/runs",
    response_model=list[AutomationWorkflowRunResponse],
)
def list_automation_workflow_runs(
    workflow_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.read")),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AutomationWorkflowRunResponse]:
    _actor, tenant_id = identity
    workflow = db.scalar(
        select(AutomationWorkflow).where(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.tenant_id == tenant_id,
        )
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    runs = db.scalars(
        select(AutomationWorkflowRun)
        .where(
            AutomationWorkflowRun.workflow_id == workflow.id,
            AutomationWorkflowRun.tenant_id == tenant_id,
        )
        .order_by(
            AutomationWorkflowRun.created_at.desc(),
            AutomationWorkflowRun.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return [automation_workflow_run_response(run) for run in runs]


@router.get(
    "/workflow-runs/{run_id}",
    response_model=AutomationWorkflowRunResponse,
)
def get_automation_workflow_run(
    run_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.workflow.read")),
) -> AutomationWorkflowRunResponse:
    _actor, tenant_id = identity
    run = db.scalar(
        select(AutomationWorkflowRun).where(
            AutomationWorkflowRun.id == run_id,
            AutomationWorkflowRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return automation_workflow_run_response(run)


def _get_agent_for_tenant(
    db: Session,
    *,
    agent_id: str,
    tenant_id: str,
) -> AIAgent:
    agent = db.scalar(
        select(AIAgent).where(
            AIAgent.id == agent_id,
            AIAgent.tenant_id == tenant_id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post(
    "/agents",
    response_model=AIAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent(
    request: AIAgentCreate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.agent.manage")),
) -> AIAgent:
    actor, tenant_id = identity
    existing = db.scalar(
        select(AIAgent).where(
            AIAgent.tenant_id == tenant_id,
            AIAgent.name == request.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Agent name already exists")

    agent = AIAgent(
        tenant_id=tenant_id,
        name=request.name,
        agent_type=request.agent_type,
        description=request.description,
        instructions=request.instructions,
        capabilities=request.capabilities,
        tools=[tool.model_dump(mode="json") for tool in request.tools],
        preferred_provider=request.preferred_provider,
        status=request.status,
        created_by=actor,
    )
    try:
        db.add(agent)
        db.flush()
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="AGENT_CREATED",
            resource_type="AIAgent",
            resource_id=agent.id,
            outcome="SUCCESS",
            detail={
                "name": agent.name,
                "agent_type": agent.agent_type,
                "status": agent.status.value,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent name already exists") from exc
    db.refresh(agent)
    return agent


@router.get("/agents", response_model=list[AIAgentResponse])
def list_agents(
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.agent.read")),
    agent_status: AgentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AIAgent]:
    _actor, tenant_id = identity
    statement = select(AIAgent).where(AIAgent.tenant_id == tenant_id)
    if agent_status is not None:
        statement = statement.where(AIAgent.status == agent_status)
    return list(
        db.scalars(
            statement.order_by(AIAgent.name.asc()).offset(offset).limit(limit)
        )
    )


@router.get("/agents/{agent_id}", response_model=AIAgentResponse)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.agent.read")),
) -> AIAgent:
    _actor, tenant_id = identity
    return _get_agent_for_tenant(db, agent_id=agent_id, tenant_id=tenant_id)


@router.patch("/agents/{agent_id}", response_model=AIAgentResponse)
def update_agent(
    agent_id: str,
    request: AIAgentUpdate,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.agent.manage")),
) -> AIAgent:
    actor, tenant_id = identity
    agent = _get_agent_for_tenant(db, agent_id=agent_id, tenant_id=tenant_id)
    updates = request.model_dump(exclude_unset=True)
    if "tools" in updates:
        updates["tools"] = [tool.model_dump(mode="json") for tool in request.tools or []]
    for field, value in updates.items():
        setattr(agent, field, value)
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="AGENT_UPDATED",
        resource_type="AIAgent",
        resource_id=agent.id,
        outcome="SUCCESS",
        detail={"fields": sorted(updates)},
    )
    db.commit()
    db.refresh(agent)
    return agent


@router.post(
    "/agents/{agent_id}/run",
    response_model=AIAgentRunResponse,
)
def run_agent(
    agent_id: str,
    request: AIAgentRunRequest,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.agent.run")),
    provider: InferenceProvider = Depends(get_inference_provider),
) -> AIAgentRunResponse:
    actor, tenant_id = identity
    agent = _get_agent_for_tenant(db, agent_id=agent_id, tenant_id=tenant_id)
    if agent.status != AgentStatus.ENABLED:
        raise HTTPException(status_code=409, detail="Agent is not enabled")
    inference = _run_inference(
        InferenceRequest(
            messages=[
                AIMessage(role="system", content=agent.instructions),
                AIMessage(role="user", content=request.prompt),
            ],
            provider=agent.preferred_provider,
            conversation_id=request.conversation_id,
            response_format=request.response_format,
            tools=[AITool.model_validate(tool) for tool in agent.tools],
        ),
        db,
        identity,
        provider,
    )
    audit(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="AGENT_RUN_COMPLETED",
        resource_type="AIAgent",
        resource_id=agent.id,
        outcome="SUCCESS",
        detail={
            "agent_type": agent.agent_type,
            "model_id": inference.model_id,
            "provider": inference.provider,
        },
    )
    db.commit()
    return AIAgentRunResponse(
        agent_id=agent.id,
        agent_name=agent.name,
        inference=inference,
    )


@router.post(
    "/agents/orchestrate",
    response_model=AIAgentOrchestrationResponse,
)
def orchestrate_agents(
    request: AIAgentOrchestrationRequest,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.agent.run")),
    provider: InferenceProvider = Depends(get_inference_provider),
) -> AIAgentOrchestrationResponse:
    actor, tenant_id = identity
    agents = [
        _get_agent_for_tenant(db, agent_id=agent_id, tenant_id=tenant_id)
        for agent_id in request.agent_ids
    ]
    if any(agent.status != AgentStatus.ENABLED for agent in agents):
        raise HTTPException(status_code=409, detail="All agents must be enabled")

    steps = []
    for agent in agents:
        inference = _run_inference(
            InferenceRequest(
                messages=[
                    AIMessage(role="system", content=agent.instructions),
                    AIMessage(role="user", content=request.prompt),
                ],
                provider=agent.preferred_provider,
                tools=[AITool.model_validate(tool) for tool in agent.tools],
            ),
            db,
            identity,
            provider,
        )
        audit(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="AGENT_RUN_COMPLETED",
            resource_type="AIAgent",
            resource_id=agent.id,
            outcome="SUCCESS",
            detail={
                "agent_type": agent.agent_type,
                "model_id": inference.model_id,
                "provider": inference.provider,
                "orchestration": True,
            },
        )
        db.commit()
        steps.append(
            AIAgentOrchestrationStep(
                agent_id=agent.id,
                agent_name=agent.name,
                content=inference.content,
            )
        )
    return AIAgentOrchestrationResponse(steps=steps)


@router.post("/ai/infer", response_model=InferenceResponse)
def infer(
    request: InferenceRequest,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.ai.infer")),
    provider: InferenceProvider = Depends(get_inference_provider),
) -> InferenceResponse:
    return _run_inference(
        request=request,
        db=db,
        identity=identity,
        provider=provider,
    )
