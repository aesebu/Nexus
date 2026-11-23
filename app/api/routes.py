from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
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
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    AIModel,
    AIModelHealthStatus,
    AIModelStatus,
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
    AIModelDiscoveryResponse,
    AIModelHealthResponse,
    AIModelResponse,
    AIModelUpdate,
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
        },
    )
    db.commit()
    db.refresh(event)
    return event


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
    stop = emergency_stop(db, tenant_id)
    if stop.active:
        raise HTTPException(status_code=409, detail="Emergency stop is active")

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
    db.commit()
    return InferenceResponse(
        model_id=model.id,
        model_name=model.name,
        provider=model.provider,
        model_identifier=model.model_identifier,
        content=result.content,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
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
