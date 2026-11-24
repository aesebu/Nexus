import json
import logging
import os
import signal
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any, Callable

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
    AutomationWorkflowRun,
    AutomationWorkflowRunStatus,
    ControlEvent,
    ControlTask,
    EmergencyStop,
    IntegrationWebhook,
    IntegrationWebhookDelivery,
    IntegrationWebhookStatus,
    TaskStatus,
    TaskWorkItem,
    WorkItemStatus,
)
from app.schemas import (
    AIMessage,
    AutomationWorkflowStep,
    InferenceRequest,
    InferenceResponse,
)
from app.integrations.webhooks import (
    WebhookConfigurationError,
    WebhookTransientError,
    send_signed_webhook,
    validate_webhook_destination,
)
from app.secrets import SecretNotFoundError, SecretStoreError, resolve_secret
from app.worker_monitoring import (
    WORKER_HEARTBEAT_INTERVAL_SECONDS,
    record_worker_heartbeat,
)

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


def _execute_webhook_delivery(
    db: Session,
    claim: WorkClaim,
    sender: Callable[..., int],
) -> dict[str, Any]:
    delivery_id = claim.payload.get("delivery_id")
    if not isinstance(delivery_id, str):
        raise PermanentWorkError("Webhook delivery identifier is invalid")
    delivery = db.scalar(
        select(IntegrationWebhookDelivery).where(
            IntegrationWebhookDelivery.id == delivery_id,
            IntegrationWebhookDelivery.tenant_id == claim.tenant_id,
            IntegrationWebhookDelivery.task_id == claim.task_id,
        )
    )
    if delivery is None:
        raise PermanentWorkError("Webhook delivery was not found")
    webhook = db.scalar(
        select(IntegrationWebhook).where(
            IntegrationWebhook.id == delivery.webhook_id,
            IntegrationWebhook.tenant_id == claim.tenant_id,
            IntegrationWebhook.status == IntegrationWebhookStatus.ENABLED,
        )
    )
    if webhook is None:
        raise PermanentWorkError("Webhook subscription is not enabled")
    event = db.scalar(
        select(ControlEvent).where(
            ControlEvent.id == delivery.event_id,
            ControlEvent.tenant_id == claim.tenant_id,
        )
    )
    if event is None:
        raise PermanentWorkError("Webhook event was not found")
    try:
        validate_webhook_destination(webhook.target_url)
    except WebhookConfigurationError as exc:
        raise PermanentWorkError(str(exc)) from exc
    try:
        signing_secret = resolve_secret(
            db,
            tenant_id=claim.tenant_id,
            name=webhook.secret_name,
        )
    except (SecretNotFoundError, SecretStoreError) as exc:
        raise PermanentWorkError("Webhook signing secret is unavailable") from exc

    try:
        body = json.dumps(
            {
                "event_id": event.id,
                "event_type": event.event_type,
                "occurred_at": event.created_at.isoformat(),
                "payload": event.payload,
            },
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PermanentWorkError("Webhook event is not JSON-compatible") from exc

    try:
        response_status = sender(
            target_url=webhook.target_url,
            signing_secret=signing_secret,
            body=body,
            event_id=event.id,
            delivery_id=delivery.id,
        )
    except WebhookConfigurationError as exc:
        raise PermanentWorkError(str(exc)) from exc
    if response_status in {408, 425, 429} or 500 <= response_status <= 599:
        raise WebhookTransientError("Webhook receiver returned a retryable status")
    if not 200 <= response_status <= 299:
        raise PermanentWorkError("Webhook receiver rejected the delivery")
    return {"status_code": response_status}


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
            workflow_run = db.scalar(
                select(AutomationWorkflowRun)
                .where(AutomationWorkflowRun.task_id == task.id)
                .with_for_update()
            )
            if workflow_run is not None:
                workflow_run.status = AutomationWorkflowRunStatus.FAILED
                workflow_run.failure_reason = task.failure_reason
                db.add(
                    AuditEvent(
                        tenant_id=workflow_run.tenant_id,
                        actor=worker_id,
                        action="WORKFLOW_RUN_FAILED",
                        resource_type="AutomationWorkflowRun",
                        resource_id=workflow_run.id,
                        outcome="FAILED",
                        detail={"reason": "MAX_ATTEMPTS_EXCEEDED"},
                    )
                )
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
        response_format=request.response_format,
        tools=request.tools,
    )
    return InferenceResponse(
        model_id=model.id,
        model_name=model.name,
        provider=model.provider,
        model_identifier=model.model_identifier,
        content=result.content,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        tool_calls=result.tool_calls or [],
        structured_output=result.structured_output,
    )


def _workflow_condition_matches(
    condition: dict[str, Any] | None,
    workflow_input: dict[str, Any],
) -> bool:
    if condition is None:
        return True
    value: Any = workflow_input
    for segment in condition["path"].split("."):
        if not isinstance(value, dict) or segment not in value:
            return False
        value = value[segment]
    return value == condition["equals"]


def _execute_workflow(
    db: Session,
    claim: WorkClaim,
    provider: InferenceProvider,
) -> dict[str, Any]:
    run_id = claim.payload.get("workflow_run_id")
    if not isinstance(run_id, str):
        raise PermanentWorkError("Workflow run identifier is invalid")
    run = db.scalar(
        select(AutomationWorkflowRun)
        .where(
            AutomationWorkflowRun.id == run_id,
            AutomationWorkflowRun.tenant_id == claim.tenant_id,
            AutomationWorkflowRun.task_id == claim.task_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise PermanentWorkError("Workflow run was not found")
    if run.status == AutomationWorkflowRunStatus.CANCELLED:
        raise PermanentWorkError("Workflow run was cancelled")
    if run.status == AutomationWorkflowRunStatus.COMPLETED:
        if run.result_snapshot is None:
            raise PermanentWorkError("Completed workflow run has no result")
        return run.result_snapshot

    task = db.scalar(
        select(ControlTask)
        .where(ControlTask.id == claim.task_id)
        .execution_options(populate_existing=True)
    )
    if task is None or task.status != TaskStatus.IN_PROGRESS:
        raise PermanentWorkError("Task is no longer active")

    run.status = AutomationWorkflowRunStatus.IN_PROGRESS
    run.failure_reason = None
    db.commit()
    step_results = list(run.step_results)
    finished_ids = {
        step_result["step_id"]
        for step_result in step_results
        if step_result["status"] in {"COMPLETED", "SKIPPED"}
    }
    workflow_input = run.input
    input_json = json.dumps(
        workflow_input,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    execution_claim = WorkClaim(
        task_id=claim.task_id,
        tenant_id=claim.tenant_id,
        work_type="ai.inference",
        payload={},
        attempt=claim.attempt,
    )
    for step_data in run.steps_snapshot:
        step = AutomationWorkflowStep.model_validate(step_data)
        if step.id in finished_ids:
            continue
        if not _workflow_condition_matches(
            step.condition.model_dump(mode="json") if step.condition else None,
            workflow_input,
        ):
            step_results.append(
                {"step_id": step.id, "status": "SKIPPED", "inference": None}
            )
        else:
            messages = []
            if step.system_prompt:
                messages.append(AIMessage(role="system", content=step.system_prompt))
            messages.append(
                AIMessage(
                    role="user",
                    content=(
                        f"{step.prompt}\n\nWorkflow input (JSON):\n{input_json}"
                    ),
                )
            )
            inference = _execute_ai_inference(
                db,
                WorkClaim(
                    task_id=execution_claim.task_id,
                    tenant_id=execution_claim.tenant_id,
                    work_type=execution_claim.work_type,
                    payload=InferenceRequest(
                        messages=messages,
                        provider=step.provider,
                        temperature=step.temperature,
                        max_tokens=step.max_tokens,
                        response_format=step.response_format,
                    ).model_dump(mode="json"),
                    attempt=execution_claim.attempt,
                ),
                provider,
            )
            step_results.append(
                {
                    "step_id": step.id,
                    "status": "COMPLETED",
                    "inference": inference.model_dump(mode="json"),
                }
            )
        run.step_results = step_results
        db.commit()
        finished_ids.add(step.id)

    result = {
        "workflow_id": run.workflow_id,
        "workflow_version": run.workflow_version,
        "steps": step_results,
    }
    run.result_snapshot = result
    db.commit()
    return result


def _finish_work_item(
    db: Session,
    *,
    claim: WorkClaim,
    worker_id: str,
    result: InferenceResponse | dict[str, Any] | None = None,
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
        result_value = (
            result.model_dump(mode="json")
            if isinstance(result, InferenceResponse)
            else result
        )
        task.result = json.dumps(result_value, ensure_ascii=False)
        task.finished_at = now
        workflow_run = db.scalar(
            select(AutomationWorkflowRun)
            .where(AutomationWorkflowRun.task_id == task.id)
            .with_for_update()
        )
        if workflow_run is not None:
            workflow_run.status = AutomationWorkflowRunStatus.COMPLETED
            workflow_run.result_snapshot = result_value
            workflow_run.failure_reason = None
            db.add(
                AuditEvent(
                    tenant_id=workflow_run.tenant_id,
                    actor=worker_id,
                    action="WORKFLOW_RUN_COMPLETED",
                    resource_type="AutomationWorkflowRun",
                    resource_id=workflow_run.id,
                    outcome="SUCCESS",
                    detail={"step_count": len(result_value.get("steps", []))},
                )
            )
        webhook_delivery = db.scalar(
            select(IntegrationWebhookDelivery).where(
                IntegrationWebhookDelivery.task_id == task.id
            )
        )
        if webhook_delivery is not None:
            db.add(
                AuditEvent(
                    tenant_id=webhook_delivery.tenant_id,
                    actor=worker_id,
                    action="WEBHOOK_DELIVERY_COMPLETED",
                    resource_type="IntegrationWebhookDelivery",
                    resource_id=webhook_delivery.id,
                    outcome="SUCCESS",
                    detail={
                        "webhook_id": webhook_delivery.webhook_id,
                        "event_id": webhook_delivery.event_id,
                        "status_code": result_value["status_code"],
                    },
                )
            )
        _audit(
            db,
            task=task,
            actor=worker_id,
            action="TASK_COMPLETED",
            outcome="SUCCESS",
            detail={
                "status": task.status.value,
                "work_type": claim.work_type,
                **(
                    {
                        "model_id": result.model_id,
                        "provider": result.provider,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                    }
                    if isinstance(result, InferenceResponse)
                    else (
                        {"step_count": len(result_value.get("steps", []))}
                        if claim.work_type == "automation.workflow"
                        else (
                            {"status_code": result_value["status_code"]}
                            if claim.work_type == "integration.webhook"
                            else {}
                        )
                    )
                ),
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
        workflow_run = db.scalar(
            select(AutomationWorkflowRun)
            .where(AutomationWorkflowRun.task_id == task.id)
            .with_for_update()
        )
        if workflow_run is not None:
            workflow_run.status = AutomationWorkflowRunStatus.FAILED
            workflow_run.failure_reason = task.failure_reason
            db.add(
                AuditEvent(
                    tenant_id=workflow_run.tenant_id,
                    actor=worker_id,
                    action="WORKFLOW_RUN_FAILED",
                    resource_type="AutomationWorkflowRun",
                    resource_id=workflow_run.id,
                    outcome="FAILED",
                    detail={"attempt": claim.attempt},
                )
            )
        webhook_delivery = db.scalar(
            select(IntegrationWebhookDelivery).where(
                IntegrationWebhookDelivery.task_id == task.id
            )
        )
        if webhook_delivery is not None:
            db.add(
                AuditEvent(
                    tenant_id=webhook_delivery.tenant_id,
                    actor=worker_id,
                    action="WEBHOOK_DELIVERY_FAILED",
                    resource_type="IntegrationWebhookDelivery",
                    resource_id=webhook_delivery.id,
                    outcome="FAILED",
                    detail={
                        "webhook_id": webhook_delivery.webhook_id,
                        "event_id": webhook_delivery.event_id,
                        "attempt": claim.attempt,
                    },
                )
            )
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
    webhook_sender: Callable[..., int] | None = None,
    now: datetime | None = None,
) -> bool:
    claimed_at = now or datetime.now(timezone.utc)
    claim = _claim_next_work_item(db, worker_id=worker_id, now=claimed_at)
    if claim is None:
        return False

    active_provider = provider or OpenAICompatibleProvider(settings)
    try:
        if claim.work_type == "ai.inference":
            result = _execute_ai_inference(db, claim, active_provider)
        elif claim.work_type == "automation.workflow":
            result = _execute_workflow(db, claim, active_provider)
        elif claim.work_type == "integration.webhook":
            result = _execute_webhook_delivery(
                db,
                claim,
                webhook_sender or send_signed_webhook,
            )
        else:
            raise PermanentWorkError("Unsupported task work type")
    except RetryableWorkError:
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            error="Emergency stop is active",
            retryable=True,
            now=datetime.now(timezone.utc),
        )
    except WebhookTransientError:
        _finish_work_item(
            db,
            claim=claim,
            worker_id=worker_id,
            error="Webhook delivery failed transiently",
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


def initialize_worker_database() -> None:
    if settings.environment != "production":
        Base.metadata.create_all(bind=engine)


def run_worker() -> None:
    initialize_worker_database()
    worker_id = (
        f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )[:128]
    logger.info("Task worker started worker_id=%s", worker_id)
    shutdown = Event()

    def request_shutdown(signum, _frame) -> None:
        logger.info("Task worker shutdown requested signal=%s", signum)
        shutdown.set()

    previous_sigint = signal.signal(signal.SIGINT, request_shutdown)
    previous_sigterm = signal.signal(signal.SIGTERM, request_shutdown)
    next_heartbeat = 0.0
    try:
        try:
            with SessionLocal() as db:
                record_worker_heartbeat(
                    db,
                    worker_id=worker_id,
                    status="RUNNING",
                )
            next_heartbeat = time.monotonic() + WORKER_HEARTBEAT_INTERVAL_SECONDS
        except SQLAlchemyError as exc:
            logger.error(
                "Task worker heartbeat failed error_type=%s",
                type(exc).__name__,
            )

        while not shutdown.is_set():
            try:
                with SessionLocal() as db:
                    if time.monotonic() >= next_heartbeat:
                        record_worker_heartbeat(
                            db,
                            worker_id=worker_id,
                            status="RUNNING",
                        )
                        next_heartbeat = (
                            time.monotonic() + WORKER_HEARTBEAT_INTERVAL_SECONDS
                        )
                    processed = process_next_work_item(db, worker_id=worker_id)
                    if time.monotonic() >= next_heartbeat:
                        record_worker_heartbeat(
                            db,
                            worker_id=worker_id,
                            status="RUNNING",
                        )
                        next_heartbeat = (
                            time.monotonic() + WORKER_HEARTBEAT_INTERVAL_SECONDS
                        )
            except SQLAlchemyError as exc:
                logger.error(
                    "Task worker database operation failed error_type=%s",
                    type(exc).__name__,
                )
                processed = False
            if not processed:
                shutdown.wait(POLL_INTERVAL_SECONDS)
    finally:
        shutdown.set()
        try:
            with SessionLocal() as db:
                record_worker_heartbeat(
                    db,
                    worker_id=worker_id,
                    status="STOPPED",
                )
        except SQLAlchemyError as exc:
            logger.error(
                "Task worker shutdown heartbeat failed error_type=%s",
                type(exc).__name__,
            )
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
