"""NEXUS REST API — CORE-01 API Gateway (Blueprint §2, §7, §9).

Wraps the in-memory `nexus_core` kernel in FastAPI. Delegates all governance
to the kernel; this layer only handles transport, auth and errors.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nexus_core import (AutonomyLevel, AuthorityLevel, CommandSpec, Nexus,
                        Principal, Risk, Step, owner)
from nexus_core.control import CommandStatus
from nexus_core.intelligence import (AgentRole, AgentState, MemoryLayer, Message)
from nexus_core.kernel import (EmergencyStopActive, InvalidTransition,
                               NotFound, PermissionDenied)


# ------------------------------------------------------------------ app state
class State:
    """One kernel per process. Swap the store for PostgreSQL later."""

    def __init__(self) -> None:
        self.nexus = Nexus()
        self.agents: dict[str, dict[str, Any]] = {}
        self.bootstrap()


state = State()
nexus = state.nexus


def bootstrap() -> None:
    """Register the command types the API exposes, plus their handlers."""
    policy = nexus.core.policy
    policy.register(CommandSpec("system.echo", "nexus.command.execute", Risk.LOW))
    policy.register(CommandSpec("system.scale", "nexus.command.execute", Risk.HIGH))
    policy.register(CommandSpec("system.wipe", "nexus.command.execute",
                                Risk.CRITICAL, reversible=False))

    nx = nexus.core
    nx.commands.register_handler("system.echo", lambda c, a: c.payload,
                                 undo=lambda c, a: None)
    nx.commands.register_handler("system.scale",
                                 lambda c, a: {"replicas": c.payload.get("replicas", 1)},
                                 undo=lambda c, a: {"replicas": 1})
    nx.commands.register_handler("system.wipe", lambda c, a: {"wiped": True})

    if os.getenv("NEXUS_ENVIRONMENT") != "production":
        # Development only: seed a tenant owner and an echo model so the API
        # is usable immediately. Never runs in production.
        boss = owner("demo", "owner-demo")
        nexus.core.models.register(boss, name="echo-chat", provider="echo",
                                   identifier="echo-1", capabilities={"chat"},
                                   priority=10)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("NEXUS_ENVIRONMENT") == "production":
        if not os.getenv("NEXUS_JWT_SECRET"):
            raise RuntimeError("NEXUS_JWT_SECRET is required in production")
    yield


app = FastAPI(title="NEXUS", description="NEXUS Supreme AI Intelligence — Core API",
              version="0.2.0", lifespan=lifespan)


# --------------------------------------------------------------- auth (§3.2)
ROLE_PERMISSIONS: dict[str, dict[str, Any]] = {
    "owner": {"authority": AuthorityLevel.HUMAN_OWNER,
              "autonomy": AutonomyLevel.L5_STRATEGIC,
              "permissions": {"nexus.*"}},
    "director": {"authority": AuthorityLevel.SYSTEM_DIRECTOR,
                 "autonomy": AutonomyLevel.L4_AUTONOMOUS_WORKFLOW,
                 "permissions": {"nexus.command.*", "nexus.system.*", "nexus.model.*",
                                 "nexus.ai.infer", "nexus.agent.*",
                                 "nexus.workflow.*", "nexus.audit.read"}},
    "operator": {"authority": AuthorityLevel.SYSTEM_DIRECTOR,
                 "autonomy": AutonomyLevel.L3_EXECUTE_APPROVED,
                 "permissions": {"nexus.command.create", "nexus.command.read",
                                 "nexus.command.execute", "nexus.ai.infer",
                                 "nexus.agent.invoke", "nexus.model.read",
                                 "nexus.audit.read"}},
    "viewer": {"authority": AuthorityLevel.SYSTEM_DIRECTOR,
               "autonomy": AutonomyLevel.L0_READ_ONLY,
               "permissions": {"nexus.audit.read"}},
}


def current_principal(
    authorization: str = Header(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_role: str = Header("viewer", alias="X-Role"),
) -> Principal:
    """Development auth: bearer token is checked for presence and shape.

    Production must replace this with real JWT verification (python-jose) —
    the kernel does not care how the Principal was established, only that
    its permissions and authority are trustworthy.
    """
    if not authorization.startswith("Bearer ") or len(authorization) < 16:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    if os.getenv("NEXUS_ENVIRONMENT") == "production":
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED,
                            "JWT verification is not implemented; refusing to run")
    role = ROLE_PERMISSIONS.get(x_role)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown role")
    return Principal(id=x_user_id, tenant_id=x_tenant_id, authority=role["authority"],
                     autonomy=role["autonomy"],
                     permissions=frozenset(role["permissions"]))


# ------------------------------------------------------------------ schemas
class CommandSubmit(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandOut(BaseModel):
    id: str
    type: str
    status: CommandStatus
    payload: dict[str, Any]
    created_by: str
    approved_by: str | None
    requires_human_approver: bool
    result: Any = None
    error: str | None = None
    history: list[list[str]]


class SystemCreate(BaseModel):
    name: str
    system_type: str
    capabilities: list[str] = Field(default_factory=list)


class ModelCreate(BaseModel):
    name: str
    provider: str
    identifier: str
    capabilities: list[str]
    priority: int = 0


class AgentCreate(BaseModel):
    name: str
    role: AgentRole
    instructions: str
    permissions: list[str] = Field(default_factory=list)
    autonomy: AutonomyLevel = AutonomyLevel.L2_RECOMMEND


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]
    temperature: float = Field(0.2, ge=0, le=2)
    max_tokens: int = Field(512, ge=1, le=8192)


class MemoryWrite(BaseModel):
    layer: MemoryLayer
    content: str
    source: str = "user"


class GoalCreate(BaseModel):
    title: str
    priority: int = 0


class WorkflowCreate(BaseModel):
    name: str
    steps: list[dict[str, Any]]


# --------------------------------------------------------------- serialisers
def cmd_out(c) -> CommandOut:
    return CommandOut(id=c.id, type=c.type, status=c.status, payload=c.payload,
                      created_by=c.created_by, approved_by=c.approved_by,
                      requires_human_approver=c.requires_human_approver,
                      result=c.result, error=c.error,
                      history=[list(h) for h in c.history])


# ------------------------------------------------------------- error mapping
@app.exception_handler(PermissionDenied)
async def denied(_r: Request, exc: PermissionDenied) -> JSONResponse:
    return JSONResponse(403, {"detail": str(exc), "error": "permission_denied"})


@app.exception_handler(NotFound)
async def missing(_r: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(404, {"detail": str(exc), "error": "not_found"})


@app.exception_handler(EmergencyStopActive)
async def stopped(_r: Request, exc: EmergencyStopActive) -> JSONResponse:
    return JSONResponse(423, {"detail": str(exc), "error": "emergency_stop"})


@app.exception_handler(InvalidTransition)
async def bad_state(_r: Request, exc: InvalidTransition) -> JSONResponse:
    return JSONResponse(409, {"detail": str(exc), "error": "invalid_transition"})


# --------------------------------------------------------------- endpoints
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "kernel": "ok"}


@app.get("/health/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "audit_chain": nexus.core.audit.verify(),
            "commands": len(nexus.core.commands._commands),
            "agents": len(nexus.core.agents._agents),
            "models": len(nexus.core.models._models)}


# --- Level 1: goals
@app.post("/api/v1/goals", status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalCreate, p: Principal = Depends(current_principal)):
    g = nexus.set_goal(p, body.title, body.priority)
    return {"id": g.id, "title": g.title, "priority": g.priority, "status": g.status}


@app.get("/api/v1/goals")
def list_goals(p: Principal = Depends(current_principal)):
    return [{"id": g.id, "title": g.title, "priority": g.priority} for g in nexus.goals(p.tenant_id)]


# --- CORE-01: commands
@app.post("/api/v1/commands", response_model=CommandOut, status_code=status.HTTP_201_CREATED)
def submit_command(body: CommandSubmit, p: Principal = Depends(current_principal)):
    return cmd_out(nexus.core.commands.submit(p, body.type, body.payload))


@app.get("/api/v1/commands", response_model=list[CommandOut])
def list_commands(p: Principal = Depends(current_principal),
                  status_filter: CommandStatus | None = Query(None, alias="status")):
    items = [c for c in nexus.core.commands._commands.values() if c.tenant_id == p.tenant_id]
    if status_filter:
        items = [c for c in items if c.status == status_filter]
    return [cmd_out(c) for c in items]


@app.get("/api/v1/commands/{command_id}", response_model=CommandOut)
def get_command(command_id: str, p: Principal = Depends(current_principal)):
    return cmd_out(nexus.core.commands.get(p.tenant_id, command_id))


@app.post("/api/v1/commands/{command_id}/approve", response_model=CommandOut)
def approve_command(command_id: str, p: Principal = Depends(current_principal)):
    return cmd_out(nexus.core.commands.approve(p, command_id))


@app.post("/api/v1/commands/{command_id}/execute", response_model=CommandOut)
def execute_command(command_id: str, p: Principal = Depends(current_principal)):
    return cmd_out(nexus.core.commands.execute(p, command_id))


@app.post("/api/v1/commands/{command_id}/cancel", response_model=CommandOut)
def cancel_command(command_id: str, p: Principal = Depends(current_principal)):
    return cmd_out(nexus.core.commands.cancel(p, command_id))


@app.post("/api/v1/commands/{command_id}/rollback", response_model=CommandOut)
def rollback_command(command_id: str, p: Principal = Depends(current_principal)):
    return cmd_out(nexus.core.commands.rollback(p, command_id))


# --- CORE-01: systems
@app.post("/api/v1/systems", status_code=status.HTTP_201_CREATED)
def register_system(body: SystemCreate, p: Principal = Depends(current_principal)):
    try:
        rec = nexus.core.systems.register(p, body.name, body.system_type, body.capabilities)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"id": rec.id, "name": rec.name, "system_type": rec.system_type,
            "capabilities": rec.capabilities, "enabled": rec.enabled}


@app.get("/api/v1/systems")
def list_systems(p: Principal = Depends(current_principal)):
    return [{"id": r.id, "name": r.name, "system_type": r.system_type,
             "capabilities": r.capabilities} for r in nexus.core.systems.list(p.tenant_id)]


# --- CORE-03: models
@app.post("/api/v1/models", status_code=status.HTTP_201_CREATED)
def register_model(body: ModelCreate, p: Principal = Depends(current_principal)):
    m = nexus.core.models.register(p, name=body.name, provider=body.provider,
                                   identifier=body.identifier,
                                   capabilities=set(body.capabilities),
                                   priority=body.priority)
    return {"id": m.id, "name": m.name, "provider": m.provider,
            "identifier": m.identifier, "capabilities": sorted(m.capabilities),
            "priority": m.priority, "health": m.health.value}


@app.get("/api/v1/models")
def list_models(p: Principal = Depends(current_principal)):
    return [{"id": m.id, "name": m.name, "provider": m.provider,
             "identifier": m.identifier, "capabilities": sorted(m.capabilities),
             "priority": m.priority, "health": m.health.value, "enabled": m.enabled}
            for m in nexus.core.models._models.values() if m.tenant_id == p.tenant_id]


@app.get("/api/v1/models/route")
def route_model(capability: str = "chat", provider: str | None = None,
                p: Principal = Depends(current_principal)):
    m = nexus.core.models.route(p.tenant_id, capability, provider)
    return {"id": m.id, "name": m.name, "provider": m.provider, "health": m.health.value}


# --- CORE-02: inference
@app.post("/api/v1/ai/infer")
def infer(body: ChatRequest, p: Principal = Depends(current_principal)):
    if nexus.core.stop.is_active(p.tenant_id):
        raise EmergencyStopActive("emergency stop is active")
    messages = [Message(m["role"], m["content"]) for m in body.messages]
    r = nexus.core.ai.infer(p, messages, temperature=body.temperature,
                            max_tokens=body.max_tokens)
    return {"content": r.content, "model_id": r.model_id,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens}


# --- CORE-04: agents
@app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED)
def create_agent(body: AgentCreate, p: Principal = Depends(current_principal)):
    a = nexus.core.agents.create(p, name=body.name, role=body.role,
                                 instructions=body.instructions,
                                 permissions=set(body.permissions),
                                 autonomy=body.autonomy)
    state.agents[a.id] = {"id": a.id, "name": a.name, "role": a.role.value,
                          "state": a.state.value}
    return state.agents[a.id]


@app.get("/api/v1/agents")
def list_agents(p: Principal = Depends(current_principal)):
    return [{"id": a.id, "name": a.name, "role": a.role.value, "state": a.state.value,
             "autonomy": a.principal.autonomy.name,
             "permissions": sorted(a.principal.permissions)}
            for a in nexus.core.agents._agents.values()
            if a.principal.tenant_id == p.tenant_id]


@app.post("/api/v1/agents/{agent_id}/invoke")
def invoke_agent(agent_id: str, body: dict[str, str], p: Principal = Depends(current_principal)):
    r = nexus.core.agents.invoke(p, agent_id, body["task"])
    return {"content": r.content, "model_id": r.model_id}


@app.post("/api/v1/agents/{agent_id}/state")
def set_agent_state(agent_id: str, body: dict[str, str], p: Principal = Depends(current_principal)):
    a = nexus.core.agents.set_state(p, agent_id, AgentState(body["state"]))
    return {"id": a.id, "state": a.state.value}


# --- CORE-05: memory
@app.post("/api/v1/memory", status_code=status.HTTP_201_CREATED)
def remember(body: MemoryWrite, p: Principal = Depends(current_principal)):
    it = nexus.core.memory.remember(p, body.layer, body.content, body.source)
    return {"id": it.id, "layer": it.layer.value, "at": it.at}


@app.get("/api/v1/memory")
def recall(q: str, limit: int = Query(5, ge=1, le=50),
           p: Principal = Depends(current_principal)):
    return [{"id": i.id, "layer": i.layer.value, "content": i.content, "at": i.at}
            for i in nexus.core.memory.recall(p, q, limit=limit)]


# --- CORE-07: workflows
@app.post("/api/v1/workflows", status_code=status.HTTP_201_CREATED)
def define_workflow(body: WorkflowCreate, p: Principal = Depends(current_principal)):
    steps = [Step(s["name"], s["command_type"], s.get("payload", {}),
                  s.get("max_attempts", 1)) for s in body.steps]
    nexus.core.workflows.define(p, body.name, steps)
    return {"name": body.name, "steps": len(steps)}


@app.post("/api/v1/workflows/{name}/run")
def run_workflow(name: str, p: Principal = Depends(current_principal)):
    run = nexus.core.workflows.run(p, name)
    return {"id": run.id, "status": run.status.value, "steps": run.step_results,
            "commands": run.command_ids, "failed_step": run.failed_step}


# --- CORE-09: governance
@app.post("/api/v1/emergency-stop")
def activate_stop(p: Principal = Depends(current_principal)):
    nexus.core.stop.activate(p)
    return {"active": True}


@app.delete("/api/v1/emergency-stop")
def clear_stop(p: Principal = Depends(current_principal)):
    nexus.core.stop.clear(p)
    return {"active": False}


@app.get("/api/v1/emergency-stop")
def stop_status(p: Principal = Depends(current_principal)):
    return {"active": nexus.core.stop.is_active(p.tenant_id)}


# --- audit
@app.get("/api/v1/audit")
def audit_events(limit: int = Query(50, ge=1, le=500),
                 p: Principal = Depends(current_principal)):
    if not p.can("nexus.audit.read"):
        raise PermissionDenied("missing nexus.audit.read")
    recs = nexus.core.audit.for_tenant(p.tenant_id)[-limit:]
    return {"chain_valid": nexus.core.audit.verify(),
            "events": [{"seq": r.seq, "actor": r.actor, "action": r.action,
                        "resource": r.resource, "outcome": r.outcome,
                        "detail": r.detail, "at": r.at} for r in recs]}


@app.get("/api/v1/events")
def event_journal(limit: int = Query(50, ge=1, le=500),
                  p: Principal = Depends(current_principal)):
    if not p.can("nexus.audit.read"):
        raise PermissionDenied("missing nexus.audit.read")
    evts = [e for e in nexus.core.events.journal if e.tenant_id == p.tenant_id][-limit:]
    return [{"type": e.type, "payload": e.payload, "source": e.source} for e in evts]
