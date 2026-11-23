"""CORE-07 Automation Engine — workflows with retry; every step is a command."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any

from .control import CommandBus, CommandStatus
from .kernel import AutonomyLevel, PermissionDenied, Principal, new_id


@dataclass(frozen=True)
class Step:
    name: str
    command_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 1


class RunStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"


@dataclass
class WorkflowRun:
    workflow: str
    status: RunStatus
    step_results: dict[str, Any] = field(default_factory=dict)
    command_ids: list[str] = field(default_factory=list)
    failed_step: str | None = None
    id: str = field(default_factory=new_id)


class WorkflowEngine:
    def __init__(self, bus: CommandBus, backoff_seconds: float = 0.0) -> None:
        self.bus = bus
        self.backoff = backoff_seconds
        self._flows: dict[tuple[str, str], list[Step]] = {}

    def define(self, actor: Principal, name: str, steps: list[Step]) -> None:
        if not actor.can("nexus.workflow.manage"):
            raise PermissionDenied("missing nexus.workflow.manage")
        self._flows[(actor.tenant_id, name)] = steps

    def run(self, actor: Principal, name: str) -> WorkflowRun:
        if not actor.is_human and actor.autonomy < AutonomyLevel.L4_AUTONOMOUS_WORKFLOW:
            raise PermissionDenied("running workflows requires autonomy L4")
        steps = self._flows.get((actor.tenant_id, name))
        if steps is None:
            raise KeyError(f"workflow {name} not found")
        run = WorkflowRun(name, RunStatus.COMPLETED)
        for step in steps:
            for attempt in range(1, step.max_attempts + 1):
                cmd = self.bus.submit(actor, step.command_type, step.payload)
                run.command_ids.append(cmd.id)
                if cmd.status == CommandStatus.PENDING_APPROVAL:
                    run.status, run.failed_step = RunStatus.WAITING_APPROVAL, step.name
                    return run
                cmd = self.bus.execute(actor, cmd.id)
                if cmd.status == CommandStatus.COMPLETED:
                    run.step_results[step.name] = cmd.result
                    break
                if attempt < step.max_attempts and self.backoff:
                    time.sleep(self.backoff * 2 ** (attempt - 1))
            else:
                run.status, run.failed_step = RunStatus.FAILED, step.name
                return run
        return run
