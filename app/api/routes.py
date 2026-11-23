from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AuditEvent, Command, CommandStatus, EmergencyStop
from app.schemas import (
    AuditResponse,
    CommandCreate,
    CommandResponse,
    EmergencyStopResponse,
)
from app.security import require_permission

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
    stop = db.scalar(select(EmergencyStop).where(EmergencyStop.tenant_id == tenant_id))
    if stop is None:
        stop = EmergencyStop(tenant_id=tenant_id, active=False)
        db.add(stop)
        db.flush()
    return stop


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

    command = Command(
        tenant_id=tenant_id,
        type=request.type,
        payload=request.payload,
        status=(
            CommandStatus.RECEIVED
            if request.require_approval
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
        detail={"type": command.type, "require_approval": request.require_approval},
    )
    db.commit()
    db.refresh(command)
    return command


@router.get("/commands/{command_id}", response_model=CommandResponse)
def get_command(
    command_id: str,
    db: Session = Depends(get_db),
    identity=Depends(require_permission("nexus.command.create")),
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
        select(Command).where(Command.id == command_id, Command.tenant_id == tenant_id)
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status != CommandStatus.RECEIVED:
        raise HTTPException(status_code=409, detail=f"Command cannot be approved from {command.status.value}")

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
        select(Command).where(Command.id == command_id, Command.tenant_id == tenant_id)
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
