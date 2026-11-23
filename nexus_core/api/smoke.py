"""Smoke test for the API without pytest/httpx.

Uses FastAPI's ASGI app directly through Starlette's TestClient when available;
otherwise this file documents the expected endpoints. Requires fastapi+httpx.
"""
import os

os.environ.setdefault("NEXUS_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from api.main import app

c = TestClient(app)
H = {"Authorization": "Bearer dev-token-1234567890", "X-Tenant-ID": "demo",
     "X-User-ID": "owner-demo", "X-Role": "owner"}

print("health :", c.get("/health").json())
print("ready  :", c.get("/health/ready").json())
cid = c.post("/api/v1/commands", headers=H,
             json={"type": "system.echo", "payload": {"ping": 1}}).json()
print("submit :", cid["status"], cid["id"][:8])
print("execute:", c.post(f"/api/v1/commands/{cid['id']}/execute", headers=H).json()["status"])
print("infer  :", c.post("/api/v1/ai/infer", headers=H,
                         json={"messages": [{"role": "user", "content": "hi NEXUS"}]}
                         ).json()["content"])
print("audit  :", c.get("/api/v1/audit", headers=H).json()["chain_valid"])
