from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings


ROLE_PERMISSIONS = {
    "owner": {
        "nexus.command.create",
        "nexus.command.read",
        "nexus.command.approve",
        "nexus.command.cancel",
        "nexus.command.execute",
        "nexus.policy.read",
        "nexus.policy.manage",
        "nexus.system.read",
        "nexus.system.manage",
        "nexus.application.read",
        "nexus.application.manage",
        "nexus.integration.read",
        "nexus.integration.manage",
        "nexus.task.read",
        "nexus.task.manage",
        "nexus.event.read",
        "nexus.event.publish",
        "nexus.config.read",
        "nexus.config.manage",
        "nexus.secret.read",
        "nexus.secret.manage",
        "nexus.model.create",
        "nexus.model.read",
        "nexus.model.update",
        "nexus.model.route",
        "nexus.ai.infer",
        "nexus.agent.read",
        "nexus.agent.manage",
        "nexus.agent.run",
        "nexus.knowledge.read",
        "nexus.knowledge.manage",
        "nexus.intelligence.read",
        "nexus.intelligence.analyze",
        "nexus.workflow.read",
        "nexus.workflow.manage",
        "nexus.workflow.run",
        "nexus.audit.read",
        "nexus.emergency.stop",
        "nexus.emergency.clear",
    },
    "operator": {
        "nexus.command.create",
        "nexus.command.read",
        "nexus.command.approve",
        "nexus.command.cancel",
        "nexus.command.execute",
        "nexus.policy.read",
        "nexus.system.read",
        "nexus.application.read",
        "nexus.integration.read",
        "nexus.task.read",
        "nexus.task.manage",
        "nexus.event.read",
        "nexus.event.publish",
        "nexus.config.read",
        "nexus.secret.read",
        "nexus.model.create",
        "nexus.model.read",
        "nexus.model.update",
        "nexus.model.route",
        "nexus.ai.infer",
        "nexus.agent.read",
        "nexus.agent.manage",
        "nexus.agent.run",
        "nexus.knowledge.read",
        "nexus.knowledge.manage",
        "nexus.intelligence.read",
        "nexus.intelligence.analyze",
        "nexus.workflow.read",
        "nexus.workflow.manage",
        "nexus.workflow.run",
        "nexus.audit.read",
    },
    "viewer": {
        "nexus.command.read",
        "nexus.system.read",
        "nexus.application.read",
        "nexus.integration.read",
        "nexus.task.read",
        "nexus.model.read",
        "nexus.agent.read",
        "nexus.knowledge.read",
        "nexus.intelligence.read",
        "nexus.workflow.read",
        "nexus.audit.read",
    },
}


def require_permission(permission: str):
    def dependency(
        authorization: str = Header(...),
        x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    ) -> tuple[str, str]:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

        token = authorization.removeprefix("Bearer ").strip()
        try:
            if settings.environment == "production":
                claims = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                    issuer=settings.jwt_issuer,
                    audience=settings.jwt_audience,
                    options={"require": ["exp", "iss", "aud"]},
                )
            else:
                claims = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                )
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

        actor = claims.get("sub")
        role = claims.get("role")
        tenant_id = claims.get("tenant_id")
        if not actor or role not in ROLE_PERMISSIONS or tenant_id != x_tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        if permission not in ROLE_PERMISSIONS[role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return actor, tenant_id

    return dependency
