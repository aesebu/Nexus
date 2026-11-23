"""CORE-01 Control Engine — command lifecycle, command bus, system registry."""
from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .governance import EmergencyStop, PolicyEngine
from .kernel import (AuditLog, EmergencyStopActive, Event, EventBus,
                     InvalidTransition, NotFound, PermissionDenied, Principal,
                     new_id, utcnow)


class CommandStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


_TRANSITIONS: dict[CommandStatus, set[CommandStatus]] = {
    CommandStatus.RECEIVED: {CommandStatus.PENDING_APPROVAL, CommandStatus.APPROVED,
                             CommandStatus.CANCELLED},
    CommandStatus.PENDING_APPROVAL: {CommandStatus.APPROVED, CommandStatus.CANCELLED},
    CommandStatus.APPROVED: {CommandStatus.EXECUTING, CommandStatus.CANCELLED},
    CommandStatus.EXECUTING: {CommandStatus.COMPLETED, CommandStatus.FAILED},
    CommandStatus.COMPLETED: {CommandStatus.ROLLED_BACK},
    CommandStatus.FAILED: set(),
    CommandStatus.CANCELLED: set(),
    CommandStatus.ROLLED_BACK: set(),
}


@dataclass
class Command:
    tenant_id: str
    type: str
    payload: dict[str, Any]
    created_by: str
    id: str = field(default_factory=new_id)
    status: CommandStatus = CommandStatus.RECEIVED
    requires_human_approver: bool = False
    approved_by: str | None = None
    result: Any = None
    error: str | None = None
    history: list[tuple[str, str, str]] = field(default_factory=list)

    def move(self, to: CommandStatus, actor: str) -> None:
        if to not in _TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.status.value} -> {to.value}")
        self.history.append((self.status.value, to.value, actor))
        self.status = to


Handler = Callable[[Command, Principal], Any]
Undo = Callable[[Command, Principal], None]


class CommandBus:
    """Submit -> (approve) -> execute -> (rollback). Every step audited."""

    def __init__(self, policy: PolicyEngine, stop: EmergencyStop,
                 audit: AuditLog, events: EventBus) -> None:
        self.policy, self.stop, self.audit, self.events = policy, stop, audit, events
        self._handlers: dict[str, tuple[Handler, Undo | None]] = {}
        self._commands: dict[str, Command] = {}
        self._lock = threading.Lock()

    def register_handler(self, command_type: str, handler: Handler,
                         undo: Undo | None = None) -> None:
        self._handlers[command_type] = (handler, undo)

    def get(self, tenant_id: str, command_id: str) -> Command:
        cmd = self._commands.get(command_id)
        if cmd is None or cmd.tenant_id != tenant_id:  # tenant isolation
            raise NotFound("command not found")
        return cmd

    def _log(self, cmd: Command, actor: str, action: str,
             outcome: str = "SUCCESS", **detail: Any) -> None:
        self.audit.record(tenant_id=cmd.tenant_id, actor=actor, action=action,
                          resource=f"command:{cmd.id}", outcome=outcome,
                          detail={"type": cmd.type, **detail})
        self.events.publish(Event(f"command.{action.lower()}", cmd.tenant_id,
                                  {"command_id": cmd.id, "status": cmd.status.value},
                                  source=actor))

    def submit(self, actor: Principal, command_type: str,
               payload: dict[str, Any] | None = None) -> Command:
        if self.stop.is_active(actor.tenant_id):
            raise EmergencyStopActive("emergency stop is active")
        decision = self.policy.evaluate(actor, command_type)
        cmd = Command(actor.tenant_id, command_type, payload or {}, actor.id)
        if not decision.allowed:
            self.audit.record(tenant_id=actor.tenant_id, actor=actor.id,
                              action="COMMAND_DENIED", resource=command_type,
                              outcome="DENIED", detail={"reason": decision.reason})
            raise PermissionDenied(decision.reason)
        cmd.requires_human_approver = decision.requires_human_approver
        with self._lock:
            self._commands[cmd.id] = cmd
        target = (CommandStatus.PENDING_APPROVAL if decision.requires_approval
                  else CommandStatus.APPROVED)
        cmd.move(target, actor.id)
        self._log(cmd, actor.id, "COMMAND_SUBMITTED", status=target.value)
        return cmd

    def approve(self, approver: Principal, command_id: str) -> Command:
        cmd = self.get(approver.tenant_id, command_id)
        reason = self.policy.check_approver(
            cmd.created_by, approver, human_required=cmd.requires_human_approver)
        if reason:
            self._log(cmd, approver.id, "COMMAND_APPROVAL_DENIED", "DENIED", reason=reason)
            raise PermissionDenied(reason)
        cmd.move(CommandStatus.APPROVED, approver.id)
        cmd.approved_by = approver.id
        self._log(cmd, approver.id, "COMMAND_APPROVED")
        return cmd

    def cancel(self, actor: Principal, command_id: str) -> Command:
        cmd = self.get(actor.tenant_id, command_id)
        if actor.id != cmd.created_by and not actor.can("nexus.command.cancel"):
            raise PermissionDenied("cannot cancel")
        cmd.move(CommandStatus.CANCELLED, actor.id)
        self._log(cmd, actor.id, "COMMAND_CANCELLED")
        return cmd

    def execute(self, actor: Principal, command_id: str) -> Command:
        cmd = self.get(actor.tenant_id, command_id)
        if self.stop.is_active(cmd.tenant_id):
            raise EmergencyStopActive("emergency stop is active")
        if not actor.can("nexus.command.execute"):
            raise PermissionDenied("missing nexus.command.execute")
        entry = self._handlers.get(cmd.type)
        if entry is None:
            raise NotFound(f"no handler for {cmd.type}")
        cmd.move(CommandStatus.EXECUTING, actor.id)
        try:
            cmd.result = entry[0](cmd, actor)
        except Exception as exc:
            cmd.error = f"{type(exc).__name__}: {exc}"
            cmd.move(CommandStatus.FAILED, actor.id)
            self._log(cmd, actor.id, "COMMAND_FAILED", "FAILED", error=cmd.error)
            return cmd
        cmd.move(CommandStatus.COMPLETED, actor.id)
        self._log(cmd, actor.id, "COMMAND_COMPLETED")
        return cmd

    def rollback(self, actor: Principal, command_id: str) -> Command:
        """§3.2 'significant changes must be reversible'."""
        cmd = self.get(actor.tenant_id, command_id)
        undo = self._handlers.get(cmd.type, (None, None))[1]
        if undo is None:
            raise InvalidTransition("command type has no undo handler")
        if not actor.can("nexus.command.execute"):
            raise PermissionDenied("missing nexus.command.execute")
        undo(cmd, actor)
        cmd.move(CommandStatus.ROLLED_BACK, actor.id)
        self._log(cmd, actor.id, "COMMAND_ROLLED_BACK")
        return cmd


@dataclass
class SystemRecord:
    tenant_id: str
    name: str
    system_type: str
    capabilities: list[str]
    id: str = field(default_factory=new_id)
    enabled: bool = True
    registered_at: str = field(default_factory=lambda: utcnow().isoformat())


class SystemRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], SystemRecord] = {}

    def register(self, actor: Principal, name: str, system_type: str,
                 capabilities: list[str]) -> SystemRecord:
        if not actor.can("nexus.system.manage"):
            raise PermissionDenied("missing nexus.system.manage")
        key = (actor.tenant_id, name)
        if key in self._items:
            raise ValueError("system name already exists")
        rec = SystemRecord(actor.tenant_id, name, system_type, capabilities)
        self._items[key] = rec
        return rec

    def list(self, tenant_id: str) -> list[SystemRecord]:
        return [r for (t, _), r in self._items.items() if t == tenant_id]
