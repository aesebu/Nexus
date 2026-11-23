from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings


ROLE_PERMISSIONS = {
    "owner": {
        "nexus.command.create",
        "nexus.command.approve",
        "nexus.command.execute",
        "nexus.audit.read",
        "nexus.emergency.stop",
        "nexus.emergency.clear",
    },
    "operator": {
        "nexus.command.create",
        "nexus.command.approve",
        "nexus.command.execute",
        "nexus.audit.read",
    },
    "viewer": {"nexus.audit.read"},
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
            claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
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
