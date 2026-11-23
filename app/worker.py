import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
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
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.models import (
    AIModel,
    AIModelStatus,
    AuditEvent,
    ControlTask,
    EmergencyStop,
    TaskStatus,
    TaskWorkItem,
    WorkItemStatus,
)
from app.schemas import InferenceRequest, InferenceResponse

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
LEASE_DURATION = timedelta(minutes=5)
POLL_INTERVAL_SECONDS = 1


@dataclass(frozen=True)
class WorkClaim:
    task_id: str
    tenant_id: str
    work_type: str
    payload: dict[str, Any]
    attempt: int


class PermanentWorkError(Exception):
    pass


class RetryableWorkError(Exception):
    pass


def _audit(
    db: Session,
    *,
    task: ControlTask,
    actor: str,
    action: str,
    outcome: str,
    detail: dict[str, Any],
) -> None:
    db.add(
        AuditEvent(
            tenant_id=task.tenant_id,
            actor=actor,
            action=action,
            resource_type="ControlTask",
            resource_id=task.id,
            outcome=outcome,
            detail=detail,
        )
    )


def _claim_next_work_item(
    db: Session,
    *,
    worker_id: str,
    now: datetime,
) -> WorkClaim | None:
    while True:
        eligible = or_(
            TaskWorkItem.status == WorkItemStatus.PENDING,
            and_(
                TaskWorkItem.status == WorkItemStatus.CLAIMED,
                TaskWorkItem.lease_expires_at <= now,
            ),
        )
        statement = (
            select(TaskWorkItem, ControlTask)
            .join(ControlTask, ControlTask.id == TaskWorkItem.task_id)
            .where(
                TaskWorkItem.tenant_id == ControlTask.tenant_id,
                eligible,
                TaskWorkItem.available_at <= now,
                ControlTask.status.in_(
                    (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
                ),
                ~select(EmergencyStop.tenant_id)
                .where(
                    EmergencyStop.tenant_id == TaskWorkItem.tenant_id,
                    EmergencyStop.active.is_(True),
                )
                .exists(),
            )
            .order_by(TaskWorkItem.available_at.asc(), ControlTask.created_at.asc())
            .with_for_update(skip_locked=True, of=TaskWorkItem)
            .limit(1)
        )
        row = db.execute(statement).first()
        if row is None:
            return None

        work_item, task = row
        if work_item.attempts >= MAX_ATTEMPTS:
            exhausted = db.execute(
                update(TaskWorkItem)
                .where(
                    TaskWorkItem.task_id == work_item.task_id,
                    eligible,
                    TaskWorkItem.available_at <= now,
                    TaskWorkItem.attempts >= MAX_ATTEMPTS,
                )
                .values(
                    status=WorkItemStatus.FAILED,
                    claimed_by=None,
                    lease_expires_at=None,
                )
                .execution_options(synchronize_session=False)
            )
            if exhausted.rowcount != 1:
                db.rollback()
                continue
            work_item.status = WorkItemStatus.FAILED
            work_item.claimed_by = None
            work_item.lease_expires_at = None
            task.status = TaskStatus.FAILED
            task.failure_reason = "Task exceeded the maximum worker attempts"
            task.finished_at = now
            _audit(
                db,
                task=task,
                actor=worker_id,
                action="TASK_FAILED",
                outcome="FAILED",
                detail={"reason": "MAX_ATTEMPTS_EXCEEDED"},
            )
            db.commit()
            continue

        claimed = db.execute(
            update(TaskWorkItem)
            .where(
                TaskWorkItem.task_id == work_item.task_id,
                eligible,
                TaskWorkItem.available_at <= now,
                TaskWorkItem.attempts < MAX_ATTEMPTS,
            )
            .values(
                status=WorkItemStatus.CLAIMED,
                attempts=TaskWorkItem.attempts + 1,
                claimed_by=worker_id,
                lease_expires_at=now + LEASE_DURATION,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.rollback()
            continue

        first_attempt = work_item.attempts == 0
        work_item.status = WorkItemStatus.CLAIMED
        work_item.attempts += 1
        work_item.claimed_by = worker_id
        work_item.lease_expires_at = now + LEASE_DURATION
        task.status = TaskStatus.IN_PROGRESS
        if task.started_at is None:
            task.started_at = now
        _audit(
            db,
            task=task,
            actor=worker_id,
            action="TASK_STARTED" if first_attempt else "TASK_RETRY_STARTED",
            outcome="SUCCESS",
            detail={
                "status": task.status.value,
                "attempt": work_item.attempts,
            },
        )
        claim = WorkClaim(
            task_id=task.id,
            tenant_id=task.tenant_id,
            work_type=work_item.work_type,
            payload=work_item.payload,
            attempt=work_item.attempts,
        )
        db.commit()
        return claim


def _execute_ai_inference(
    db: Session,
    claim: WorkClaim,
    provider: InferenceProvider,
) -> InferenceResponse:
    task = db.scalar(
        select(ControlTask)
        .where(ControlTask.id == claim.task_id)
        .execution_options(populate_existing=True)
    )
    if task is None or task.status != TaskStatus.IN_PROGRESS:
        raise PermanentWorkError("Task is no longer active")

    stop = db.scalar(
        select(EmergencyStop).where(EmergencyStop.tenant_id == claim.tenant_id)
    )
    if stop is not None and stop.active:
        raise RetryableWorkError("Emergency stop is active")

    request = InferenceRequest.model_validate(claim.payload)
    statement = (
        select(AIModel)
        .where(
            AIModel.tenant_id == claim.tenant_id,
            AIModel.status == AIModelStatus.ENABLED,
        )
        .order_by(AIModel.priority.desc(), AIModel.name.asc())
    )
    if request.provider is not None:
        statement = statement.where(AIModel.provider == request.provider)
    model = next(
        (
            candidate
            for candidate in db.scalars(statement)
            if "chat" in candidate.capabilities
        ),
        None,
    )
    if model is None:
        raise PermanentWorkError("No enabled chat model is registered")
    if model.provider != provider.provider_name:
        raise PermanentWorkError(
            f"Provider {model.provider} is not supported by this worker"
        )

    result = provider.generate(
        model_identifier=model.model_identifier,
        messages=request.messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    return InferenceResponse(
        model_id=model.id,
        model_name=model.name,
        provider=model.provider,
        model_identifier=model.model_identifier,
        content=result.content,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def _finish_work_item(
    db: Session,
    *,
    claim: WorkClaim,
    worker_id: str,
    result: InferenceResponse | None = None,
    error: str | None = None,
    retryable: bool = False,
    now: datetime,
) -> None:
    work_item = db.scalar(
        select(TaskWorkItem)
        .where(TaskWorkItem.task_id == claim.task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    task = db.scalar(
        select(ControlTask)
        .where(ControlTask.id == claim.task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        work_item is None
        or task is None
        or work_item.status != WorkItemStatus.CLAIMED
        or work_item.claimed_by != worker_id
        or task.status != TaskStatus.IN_PROGRESS
    ):
        return

    work_item.claimed_by = None
    work_item.lease_expires_at = None
    if result is not None:
        work_item.status = WorkItemStatus.COMPLETED
        task.status = TaskStatus.COMPLETED
        task.result = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        task.finished_at = now
        _audit(
            db,
            task=task,
            actor=worker_id,
            action="TASK_COMPLETED",
            outcome="SUCCESS",
            detail={
                "status": task.status.value,
                "work_type": claim.work_type,
                "model_id": result.model_id,
                "provider": result.provider,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
    elif retryable and claim.attempt < MAX_ATTEMPTS:
        work_item.status = WorkItemStatus.PENDING
        retry_delay = min(5 * (2 ** (claim.attempt - 1)), 60)
        work_item.available_at = now + timedelta(seconds=retry_delay)
        _audit(
            db,
            task=task,
            actor=worker_id,
            action="TASK_RETRY_SCHEDULED",
            outcome="RETRY",
            detail={
                "attempt": claim.attempt,
                "retry_delay_seconds": retry_delay,
            },
        )
    else:
        work_item.status = WorkItemStatus.FAILED
        task.status = TaskStatus.FAILED
        task.failure_reason = error or "Task execution failed"
        task.finished_at = now
        _audit(
            db,
            task=task,
            actor=worker_id,
            action="TASK_FAILED",
            outcome="FAILED",
            detail={
                "reason": "WORKER_EXECUTION_FAILED",
                "attempt": claim.attempt,
            },
        )
    db.commit()


def process_next_work_item(
    db: Session,
    *,
    worker_id: str,
    provider: InferenceProvider | None = None,
    now: datetime | None = None,
) -> bool:
    claimed_at = now or datetime.now(timezone.utc)
    claim = _claim_next_work_item(db, worker_id=worker_id, now=claimed_at)
    if claim is None:
        return False

    active_provider = provider or OpenAICompatibleProvider(settings)
    try:
        if claim.work_type != "ai.inference":
            raise PermanentWorkError("Unsupported task work type")
        result = _execute_ai_inference(db, claim, active_provider)
    except RetryableWorkError:
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            error="Emergency stop is active",
            retryable=True,
            now=datetime.now(timezone.utc),
        )
    except (ProviderTimeoutError, ProviderRequestError):
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            error="AI provider request failed",
            retryable=True,
            now=datetime.now(timezone.utc),
        )
    except (
        PermanentWorkError,
        ProviderNotConfiguredError,
        ProviderResponseError,
        UnsupportedProviderError,
    ) as exc:
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            error=str(exc),
            now=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.error(
            "Task execution failed task_id=%s error_type=%s",
            claim.task_id,
            type(exc).__name__,
        )
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            error="Task execution failed due to an internal error",
            now=datetime.now(timezone.utc),
        )
    else:
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            result=result,
            now=datetime.now(timezone.utc),
        )
    return True


def run_worker() -> None:
    Base.metadata.create_all(bind=engine)
    worker_id = (
        f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )[:128]
    logger.info("Task worker started worker_id=%s", worker_id)
    while True:
        try:
            with SessionLocal() as db:
                processed = process_next_work_item(db, worker_id=worker_id)
        except SQLAlchemyError as exc:
            logger.error(
                "Task worker database operation failed error_type=%s",
                type(exc).__name__,
            )
            processed = False
        if not processed:
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
