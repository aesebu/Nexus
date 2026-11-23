"""CORE-09 Security & Governance — policy engine + emergency stop (§3.2, §9)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .kernel import (AuditLog, AuthorityLevel, AutonomyLevel, Principal,
                     Risk, utcnow)


@dataclass(frozen=True)
class CommandSpec:
    """Declares what a command type needs. Unknown types are denied."""
    type: str
    permission: str
    risk: Risk = Risk.LOW
    min_autonomy: AutonomyLevel = AutonomyLevel.L3_EXECUTE_APPROVED
    reversible: bool = True


@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_approval: bool
    requires_human_approver: bool
    reason: str


@dataclass
class PolicyEngine:
    """Fail-closed: no spec registered => deny."""
    specs: dict[str, CommandSpec] = field(default_factory=dict)

    def register(self, spec: CommandSpec) -> None:
        self.specs[spec.type] = spec

    def evaluate(self, actor: Principal, command_type: str) -> Decision:
        spec = self.specs.get(command_type)
        if spec is None:
            return Decision(False, False, False, "unknown command type (fail-closed)")
        if not actor.can(spec.permission):
            return Decision(False, False, False, f"missing permission {spec.permission}")
        if not actor.is_human and actor.autonomy < spec.min_autonomy:
            return Decision(False, False, False,
                            f"autonomy {actor.autonomy.name} < {spec.min_autonomy.name}")

        human_needed = spec.risk == Risk.CRITICAL or not spec.reversible
        needs_approval = (
            spec.risk >= Risk.HIGH
            or human_needed
            # below L4, non-humans only run *approved* tasks (§3.3 L3)
            or (not actor.is_human and actor.autonomy < AutonomyLevel.L4_AUTONOMOUS_WORKFLOW)
        )
        return Decision(True, needs_approval, human_needed, "allowed")

    @staticmethod
    def check_approver(creator_id: str, approver: Principal, *,
                       human_required: bool) -> str | None:
        """Return a denial reason, or None if the approver is valid."""
        if approver.id == creator_id:
            return "separation of duties: creator cannot approve"
        if not approver.can("nexus.command.approve"):
            return "approver lacks nexus.command.approve"
        if approver.authority >= AuthorityLevel.AI_AGENT:
            return "agents and tools cannot approve"
        if human_required and not approver.is_human:
            return "this command requires a human owner approval"
        return None


class EmergencyStop:
    """Per-tenant kill switch. Only humans may clear it."""

    def __init__(self, audit: AuditLog) -> None:
        self._active: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()
        self._audit = audit

    def is_active(self, tenant_id: str) -> bool:
        return tenant_id in self._active

    def activate(self, actor: Principal) -> None:
        if not actor.can("nexus.emergency.stop"):
            from .kernel import PermissionDenied
            raise PermissionDenied("cannot activate emergency stop")
        with self._lock:
            self._active[actor.tenant_id] = (actor.id, utcnow().isoformat())
        self._audit.record(tenant_id=actor.tenant_id, actor=actor.id,
                           action="EMERGENCY_STOP_ACTIVATED", resource="tenant")

    def clear(self, actor: Principal) -> None:
        from .kernel import PermissionDenied
        if not actor.is_human or not actor.can("nexus.emergency.clear"):
            raise PermissionDenied("only a human owner can clear emergency stop")
        with self._lock:
            self._active.pop(actor.tenant_id, None)
        self._audit.record(tenant_id=actor.tenant_id, actor=actor.id,
                           action="EMERGENCY_STOP_CLEARED", resource="tenant")
