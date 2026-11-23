"""NEXUS Kernel — shared primitives (Blueprint §3, §9).

Framework-agnostic: no FastAPI / DB dependency, so every rule is unit-testable.
"""
from __future__ import annotations

import enum
import hashlib
import json
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- errors
class NexusError(Exception):
    """Base error."""


class PermissionDenied(NexusError):
    pass


class EmergencyStopActive(NexusError):
    pass


class InvalidTransition(NexusError):
    pass


class NotFound(NexusError):
    pass


# ------------------------------------------------------- authority (§3.1)
class AuthorityLevel(enum.IntEnum):
    """Lower value = higher authority."""
    HUMAN_OWNER = 0
    NEXUS = 1
    NEXUS_CORE = 2
    SYSTEM_DIRECTOR = 3
    AI_AGENT = 4
    TOOL = 5


class AutonomyLevel(enum.IntEnum):
    """§3.3 — higher value = more autonomy."""
    L0_READ_ONLY = 0
    L1_ANALYZE = 1
    L2_RECOMMEND = 2
    L3_EXECUTE_APPROVED = 3
    L4_AUTONOMOUS_WORKFLOW = 4
    L5_STRATEGIC = 5


class Risk(enum.IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(frozen=True)
class Principal:
    """Any actor: human, NEXUS, agent or tool. Immutable — nobody edits
    their own privileges in place (§3.2 'no self-granted privileges')."""
    id: str
    tenant_id: str
    authority: AuthorityLevel
    autonomy: AutonomyLevel
    permissions: frozenset[str] = frozenset()

    @property
    def is_human(self) -> bool:
        return self.authority == AuthorityLevel.HUMAN_OWNER

    def can(self, permission: str) -> bool:
        if permission in self.permissions:
            return True
        # wildcard: "nexus.command.*"
        return any(p.endswith(".*") and permission.startswith(p[:-1])
                   for p in self.permissions)


# ----------------------------------------------------------- audit (§9)
@dataclass(frozen=True)
class AuditRecord:
    seq: int
    tenant_id: str
    actor: str
    action: str
    resource: str
    outcome: str
    detail: dict[str, Any]
    at: str
    prev_hash: str
    hash: str


class AuditLog:
    """Append-only, hash-chained log. `verify()` detects tampering."""

    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def record(self, *, tenant_id: str, actor: str, action: str,
               resource: str, outcome: str = "SUCCESS",
               detail: dict[str, Any] | None = None) -> AuditRecord:
        with self._lock:
            prev = self._records[-1].hash if self._records else self.GENESIS
            body = {
                "seq": len(self._records), "tenant_id": tenant_id,
                "actor": actor, "action": action, "resource": resource,
                "outcome": outcome, "detail": detail or {},
                "at": utcnow().isoformat(), "prev_hash": prev,
            }
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode()
            ).hexdigest()
            rec = AuditRecord(**body, hash=digest)
            self._records.append(rec)
            return rec

    def for_tenant(self, tenant_id: str) -> list[AuditRecord]:
        return [r for r in self._records if r.tenant_id == tenant_id]

    def verify(self) -> bool:
        prev = self.GENESIS
        for r in self._records:
            body = {k: getattr(r, k) for k in (
                "seq", "tenant_id", "actor", "action", "resource",
                "outcome", "detail", "at", "prev_hash")}
            if r.prev_hash != prev:
                return False
            if hashlib.sha256(json.dumps(body, sort_keys=True, default=str)
                              .encode()).hexdigest() != r.hash:
                return False
            prev = r.hash
        return True


# --------------------------------------------------------- events (CORE-01)
@dataclass(frozen=True)
class Event:
    type: str
    tenant_id: str
    payload: dict[str, Any]
    source: str
    id: str = field(default_factory=new_id)
    at: datetime = field(default_factory=utcnow)


class EventBus:
    """In-process pub/sub. A failing subscriber never breaks the publisher."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self.journal: list[Event] = []
        self.errors: list[tuple[Event, Exception]] = []

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subs[event_type].append(handler)

    def publish(self, event: Event) -> None:
        self.journal.append(event)
        for h in self._subs.get(event.type, []) + self._subs.get("*", []):
            try:
                h(event)
            except Exception as exc:  # isolate subscribers
                self.errors.append((event, exc))
