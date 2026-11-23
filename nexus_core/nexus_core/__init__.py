"""NEXUS Core — the three-tier facade (Blueprint §2).

    LEVEL 1  NEXUS        -> Nexus.decide()      (goals / strategy)
    LEVEL 2  NEXUS CORE   -> Nexus.core.*        (control, models, agents, memory)
    LEVEL 3  NEXUS SYSTEM -> handlers / workflows (execution)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .automation import Step, WorkflowEngine
from .control import CommandBus, SystemRegistry
from .governance import CommandSpec, EmergencyStop, PolicyEngine
from .intelligence import (AgentEngine, AIEngine, EchoProvider, MemoryStore,
                           ModelRegistry)
from .kernel import (AuditLog, AuthorityLevel, AutonomyLevel, EventBus,
                     Principal, Risk, new_id)

__all__ = ["Nexus", "Principal", "AuthorityLevel", "AutonomyLevel", "Risk",
           "CommandSpec", "Step", "owner", "ALL_PERMISSIONS"]

ALL_PERMISSIONS = frozenset({
    "nexus.command.*", "nexus.system.manage", "nexus.model.manage",
    "nexus.ai.infer", "nexus.agent.manage", "nexus.agent.invoke",
    "nexus.workflow.manage", "nexus.emergency.stop", "nexus.emergency.clear",
    "nexus.goal.manage",
})


def owner(tenant_id: str, user_id: str | None = None) -> Principal:
    """Level 0 — Human Owner."""
    return Principal(user_id or new_id(), tenant_id, AuthorityLevel.HUMAN_OWNER,
                     AutonomyLevel.L5_STRATEGIC, ALL_PERMISSIONS)


@dataclass
class Goal:
    tenant_id: str
    title: str
    priority: int
    owner: str
    id: str = field(default_factory=new_id)
    status: str = "ACTIVE"


@dataclass
class Core:
    audit: AuditLog
    events: EventBus
    policy: PolicyEngine
    stop: EmergencyStop
    commands: CommandBus
    systems: SystemRegistry
    models: ModelRegistry
    ai: AIEngine
    memory: MemoryStore
    agents: AgentEngine
    workflows: WorkflowEngine


class Nexus:
    """Level 1. Holds goals and wires Level 2. In-memory now; each component
    sits behind a small interface so a DB/FastAPI layer can replace it."""

    def __init__(self) -> None:
        audit, events = AuditLog(), EventBus()
        policy = PolicyEngine()
        stop = EmergencyStop(audit)
        bus = CommandBus(policy, stop, audit, events)
        models = ModelRegistry()
        ai = AIEngine(models, audit)
        ai.add_provider(EchoProvider())
        memory = MemoryStore()
        self.core = Core(audit, events, policy, stop, bus, SystemRegistry(),
                         models, ai, memory, AgentEngine(ai, memory, audit),
                         WorkflowEngine(bus))
        self._goals: dict[str, Goal] = {}

    # ---- Level 1: goals & prioritisation
    def set_goal(self, actor: Principal, title: str, priority: int = 0) -> Goal:
        if not actor.can("nexus.goal.manage"):
            from .kernel import PermissionDenied
            raise PermissionDenied("missing nexus.goal.manage")
        g = Goal(actor.tenant_id, title, priority, actor.id)
        self._goals[g.id] = g
        self.core.audit.record(tenant_id=actor.tenant_id, actor=actor.id,
                               action="GOAL_SET", resource=f"goal:{g.id}",
                               detail={"title": title, "priority": priority})
        return g

    def goals(self, tenant_id: str) -> list[Goal]:
        return sorted((g for g in self._goals.values()
                       if g.tenant_id == tenant_id and g.status == "ACTIVE"),
                      key=lambda g: -g.priority)
