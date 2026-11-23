"""CORE-02 AI Engine, CORE-03 Model Intelligence, CORE-04 Agent Engine,
CORE-05 Memory. Providers are pluggable via the `Provider` protocol."""
from __future__ import annotations

import enum
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from .kernel import (AuditLog, AuthorityLevel, AutonomyLevel, NexusError,
                     NotFound, PermissionDenied, Principal, new_id, utcnow)


# ------------------------------------------------- CORE-03 Model Intelligence
class Health(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class ModelRecord:
    tenant_id: str
    name: str
    provider: str
    identifier: str
    capabilities: set[str]
    priority: int = 0
    enabled: bool = True
    health: Health = Health.UNKNOWN
    id: str = field(default_factory=new_id)


class NoModelAvailable(NexusError):
    pass


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelRecord] = {}

    def register(self, actor: Principal, **kw: Any) -> ModelRecord:
        if not actor.can("nexus.model.manage"):
            raise PermissionDenied("missing nexus.model.manage")
        m = ModelRecord(tenant_id=actor.tenant_id, **kw)
        self._models[m.id] = m
        return m

    def mark_health(self, model_id: str, health: Health) -> None:
        self._models[model_id].health = health

    def route(self, tenant_id: str, capability: str,
              provider: str | None = None) -> ModelRecord:
        """Deterministic: enabled, has capability, not UNHEALTHY,
        highest priority, then name."""
        candidates = [
            m for m in self._models.values()
            if m.tenant_id == tenant_id and m.enabled
            and capability in m.capabilities and m.health != Health.UNHEALTHY
            and (provider is None or m.provider == provider)
        ]
        if not candidates:
            raise NoModelAvailable(f"no model for capability '{capability}'")
        return sorted(candidates, key=lambda m: (-m.priority, m.name))[0]

    def fallbacks(self, tenant_id: str, capability: str) -> list[ModelRecord]:
        ms = [m for m in self._models.values()
              if m.tenant_id == tenant_id and m.enabled
              and capability in m.capabilities and m.health != Health.UNHEALTHY]
        return sorted(ms, key=lambda m: (-m.priority, m.name))


# --------------------------------------------------------- CORE-02 AI Engine
@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass(frozen=True)
class Completion:
    content: str
    model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    name: str

    def generate(self, identifier: str, messages: list[Message],
                 temperature: float, max_tokens: int) -> tuple[str, int | None, int | None]: ...


class EchoProvider:
    """Offline provider for tests/dev. Replace with an OpenAI-compatible one."""
    name = "echo"

    def generate(self, identifier, messages, temperature, max_tokens):
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return f"[{identifier}] {last}"[:max_tokens * 4], len(last.split()), None


class AIEngine:
    """Routes to a model, falls back on failure, audits usage (never content)."""

    def __init__(self, models: ModelRegistry, audit: AuditLog) -> None:
        self.models, self.audit = models, audit
        self.providers: dict[str, Provider] = {}

    def add_provider(self, provider: Provider) -> None:
        self.providers[provider.name] = provider

    def infer(self, actor: Principal, messages: list[Message], *,
              capability: str = "chat", temperature: float = 0.2,
              max_tokens: int = 512) -> Completion:
        if not actor.can("nexus.ai.infer"):
            raise PermissionDenied("missing nexus.ai.infer")
        if not 0 <= temperature <= 2 or not 1 <= max_tokens <= 8192:
            raise ValueError("temperature 0-2, max_tokens 1-8192")
        last_error: Exception | None = None
        for model in self.models.fallbacks(actor.tenant_id, capability):
            provider = self.providers.get(model.provider)
            if provider is None:
                continue
            try:
                text, tin, tout = provider.generate(
                    model.identifier, messages, temperature, max_tokens)
            except Exception as exc:
                last_error = exc
                self.models.mark_health(model.id, Health.UNHEALTHY)
                continue
            self.models.mark_health(model.id, Health.HEALTHY)
            self.audit.record(tenant_id=actor.tenant_id, actor=actor.id,
                              action="AI_INFERENCE", resource=f"model:{model.id}",
                              detail={"input_tokens": tin, "output_tokens": tout})
            return Completion(text, model.id, tin, tout)
        raise NoModelAvailable(f"all models failed: {last_error}")


# ------------------------------------------------------- CORE-05 Memory
class MemoryLayer(str, enum.Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class MemoryItem:
    tenant_id: str
    owner: str
    layer: MemoryLayer
    content: str
    source: str
    id: str = field(default_factory=new_id)
    version: int = 1
    at: str = field(default_factory=lambda: utcnow().isoformat())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class MemoryStore:
    """Tenant + owner isolated. Keyword retrieval now; swap for pgvector later."""

    def __init__(self) -> None:
        self._items: dict[str, list[MemoryItem]] = defaultdict(list)

    def remember(self, actor: Principal, layer: MemoryLayer, content: str,
                 source: str = "user") -> MemoryItem:
        item = MemoryItem(actor.tenant_id, actor.id, layer, content, source)
        self._items[actor.tenant_id].append(item)
        return item

    def recall(self, actor: Principal, query: str, *, limit: int = 5,
               layers: set[MemoryLayer] | None = None,
               include_shared: bool = True) -> list[MemoryItem]:
        q = _tokens(query)
        scored = []
        for it in self._items.get(actor.tenant_id, []):
            if layers and it.layer not in layers:
                continue
            shared = it.layer in (MemoryLayer.SEMANTIC, MemoryLayer.LONG_TERM)
            if it.owner != actor.id and not (include_shared and shared):
                continue
            score = len(q & _tokens(it.content))
            if score:
                scored.append((score, it.at, it))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [s[2] for s in scored[:limit]]

    def clear_working(self, actor: Principal) -> int:
        items = self._items.get(actor.tenant_id, [])
        keep = [i for i in items if not (i.owner == actor.id
                                         and i.layer == MemoryLayer.WORKING)]
        removed = len(items) - len(keep)
        self._items[actor.tenant_id] = keep
        return removed


# ------------------------------------------------------- CORE-04 Agent Engine
class AgentRole(str, enum.Enum):
    EXECUTIVE = "executive"
    RESEARCH = "research"
    ANALYSIS = "analysis"
    DEVELOPMENT = "development"
    OPERATIONS = "operations"
    QA = "qa"
    SECURITY = "security"
    SPECIALIZED = "specialized"


class AgentState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


@dataclass
class Agent:
    principal: Principal
    name: str
    role: AgentRole
    instructions: str
    created_by: str
    state: AgentState = AgentState.ACTIVE

    @property
    def id(self) -> str:
        return self.principal.id


class AgentEngine:
    """Agents are created by someone with higher authority and can never hold
    more permissions or autonomy than their creator (§3.2)."""

    def __init__(self, ai: AIEngine, memory: MemoryStore, audit: AuditLog) -> None:
        self.ai, self.memory, self.audit = ai, memory, audit
        self._agents: dict[str, Agent] = {}

    def create(self, creator: Principal, *, name: str, role: AgentRole,
               instructions: str, permissions: set[str],
               autonomy: AutonomyLevel) -> Agent:
        if not creator.can("nexus.agent.manage"):
            raise PermissionDenied("missing nexus.agent.manage")
        if creator.authority >= AuthorityLevel.AI_AGENT:
            raise PermissionDenied("agents cannot create agents in this phase")
        excess = {p for p in permissions if not creator.can(p)}
        if excess:
            raise PermissionDenied(f"cannot delegate permissions you lack: {sorted(excess)}")
        if not creator.is_human and autonomy > creator.autonomy:
            raise PermissionDenied("cannot delegate more autonomy than you hold")
        principal = Principal(new_id(), creator.tenant_id, AuthorityLevel.AI_AGENT,
                              autonomy, frozenset(permissions))
        agent = Agent(principal, name, role, instructions, creator.id)
        self._agents[agent.id] = agent
        self.audit.record(tenant_id=creator.tenant_id, actor=creator.id,
                          action="AGENT_CREATED", resource=f"agent:{agent.id}",
                          detail={"role": role.value, "autonomy": autonomy.name,
                                  "permissions": sorted(permissions)})
        return agent

    def get(self, tenant_id: str, agent_id: str) -> Agent:
        a = self._agents.get(agent_id)
        if a is None or a.principal.tenant_id != tenant_id:
            raise NotFound("agent not found")
        return a

    def set_state(self, actor: Principal, agent_id: str, state: AgentState) -> Agent:
        a = self.get(actor.tenant_id, agent_id)
        if not actor.can("nexus.agent.manage") or actor.id == a.id:
            raise PermissionDenied("cannot change this agent's state")
        a.state = state
        self.audit.record(tenant_id=actor.tenant_id, actor=actor.id,
                          action=f"AGENT_{state.value}", resource=f"agent:{a.id}")
        return a

    def invoke(self, caller: Principal, agent_id: str, task: str) -> Completion:
        """Run the agent on a task with its own identity + recalled memory."""
        agent = self.get(caller.tenant_id, agent_id)
        if agent.state != AgentState.ACTIVE:
            raise PermissionDenied(f"agent is {agent.state.value}")
        if not caller.can("nexus.agent.invoke"):
            raise PermissionDenied("missing nexus.agent.invoke")
        context = self.memory.recall(agent.principal, task, limit=3)
        system = agent.instructions
        if context:
            system += "\n\nRelevant memory:\n" + "\n".join(f"- {m.content}" for m in context)
        result = self.ai.infer(agent.principal, [Message("system", system),
                                                 Message("user", task)])
        self.memory.remember(agent.principal, MemoryLayer.EPISODIC,
                             f"task: {task}", source=f"invoke:{caller.id}")
        return result
