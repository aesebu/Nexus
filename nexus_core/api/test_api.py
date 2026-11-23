"""API tests. Run with FastAPI's TestClient (requires httpx)."""
import os

from fastapi.testclient import TestClient

os.environ.setdefault("NEXUS_ENVIRONMENT", "development")

from api.main import app  # noqa: E402

client = TestClient(app)

OWNER = {"Authorization": "Bearer dev-token-1234567890",
         "X-Tenant-ID": "demo", "X-User-ID": "owner-demo", "X-Role": "owner"}
OWNER2 = {**OWNER, "X-User-ID": "owner-two"}
OTHER = {**OWNER, "X-Tenant-ID": "other"}
VIEWER = {**OWNER, "X-Role": "viewer"}


def test_health_and_ready():
    assert client.get("/health").json()["status"] == "healthy"
    assert client.get("/health/ready").json()["audit_chain"] is True


def test_auth_required():
    assert client.get("/api/v1/goals").status_code == 422          # missing headers
    assert client.get("/api/v1/goals", headers={"Authorization": "x"}).status_code == 401


def test_low_risk_command_flow():
    r = client.post("/api/v1/commands", headers=OWNER,
                    json={"type": "system.echo", "payload": {"hello": "world"}})
    assert r.status_code == 201 and r.json()["status"] == "APPROVED"
    cid = r.json()["id"]
    done = client.post(f"/api/v1/commands/{cid}/execute", headers=OWNER).json()
    assert done["status"] == "COMPLETED" and done["result"] == {"hello": "world"}


def test_unknown_command_fail_closed():
    r = client.post("/api/v1/commands", headers=OWNER, json={"type": "bogus"})
    assert r.status_code == 403


def test_high_risk_needs_second_approver():
    cid = client.post("/api/v1/commands", headers=OWNER,
                      json={"type": "system.scale", "payload": {"replicas": 5}}).json()["id"]
    assert client.post(f"/api/v1/commands/{cid}/approve", headers=OWNER).status_code == 403
    assert client.post(f"/api/v1/commands/{cid}/approve", headers=OWNER2).status_code == 200
    done = client.post(f"/api/v1/commands/{cid}/execute", headers=OWNER).json()
    assert done["result"] == {"replicas": 5}


def test_critical_needs_human():
    cid = client.post("/api/v1/commands", headers=OWNER, json={"type": "system.wipe"}).json()["id"]
    director = {**OWNER, "X-Role": "director"}
    assert client.post(f"/api/v1/commands/{cid}/approve", headers=director).status_code == 403
    assert client.post(f"/api/v1/commands/{cid}/approve", headers=OWNER2).status_code == 200


def test_tenant_isolation():
    cid = client.post("/api/v1/commands", headers=OWNER, json={"type": "system.echo"}).json()["id"]
    assert client.get(f"/api/v1/commands/{cid}", headers=OTHER).status_code == 404
    assert all(c["id"] != cid for c in client.get("/api/v1/commands", headers=OTHER).json())


def test_emergency_stop_blocks_then_clears():
    assert client.post("/api/v1/emergency-stop", headers=OWNER).status_code == 200
    assert client.post("/api/v1/commands", headers=OWNER,
                       json={"type": "system.echo"}).status_code == 423
    assert client.delete("/api/v1/emergency-stop", headers=OWNER).status_code == 200
    assert client.post("/api/v1/commands", headers=OWNER,
                       json={"type": "system.echo"}).status_code == 201


def test_inference_and_agent():
    assert client.post("/api/v1/ai/infer", headers=OWNER,
                       json={"messages": [{"role": "user", "content": "hi"}]}
                       ).status_code == 200
    a = client.post("/api/v1/agents", headers=OWNER,
                    json={"name": "R", "role": "research", "instructions": "research",
                          "permissions": ["nexus.ai.infer"], "autonomy": 2}).json()
    r = client.post(f"/api/v1/agents/{a['id']}/invoke", headers=OWNER, json={"task": "sizing"})
    assert r.status_code == 200 and "sizing" in r.json()["content"]


def test_workflow_runs_and_pauses():
    client.post("/api/v1/workflows", headers=OWNER,
                json={"name": "wf", "steps": [{"name": "e", "command_type": "system.echo",
                                               "payload": {"n": 1}}]})
    run = client.post("/api/v1/workflows/wf/run", headers=OWNER).json()
    assert run["status"] == "COMPLETED" and run["steps"] == {"e": {"n": 1}}

    client.post("/api/v1/workflows", headers=OWNER,
                json={"name": "risk", "steps": [{"name": "s", "command_type": "system.scale"}]})
    assert client.post("/api/v1/workflows/risk/run", headers=OWNER).json()["status"] == "WAITING_APPROVAL"


def test_memory_isolated_and_queryable():
    client.post("/api/v1/memory", headers=OWNER,
                json={"layer": "working", "content": "budget plan 2026"})
    hits = client.get("/api/v1/memory?q=budget", headers=OWNER).json()
    assert hits and "budget" in hits[0]["content"]
    assert client.get("/api/v1/memory?q=budget", headers=OTHER).json() == []


def test_audit_chain_and_viewer_readonly():
    log = client.get("/api/v1/audit", headers=OWNER).json()
    assert log["chain_valid"] is True and len(log["events"]) > 0
    assert client.post("/api/v1/commands", headers=VIEWER,
                       json={"type": "system.echo"}).status_code == 403
    assert client.post("/api/v1/emergency-stop", headers=VIEWER).status_code == 403


def test_goals():
    client.post("/api/v1/goals", headers=OWNER, json={"title": "Ship MVP", "priority": 5})
    titles = [g["title"] for g in client.get("/api/v1/goals", headers=OWNER).json()]
    assert "Ship MVP" in titles
