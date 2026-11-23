from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import CommandStatus


class CommandCreate(BaseModel):
    type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    require_approval: bool = True


class CommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    type: str
    payload: dict[str, Any]
    status: CommandStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    result: str | None


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    detail: dict[str, Any]
    created_at: datetime


class EmergencyStopResponse(BaseModel):
    tenant_id: str
    active: bool
    activated_by: str | None
    activated_at: datetime | None
