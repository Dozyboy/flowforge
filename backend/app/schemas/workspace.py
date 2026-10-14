import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import EmailStr, Field

from app.core.permissions import Role
from app.schemas.auth import UserOut
from app.schemas.common import ApiModel


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    created_at: datetime


class MemberOut(ApiModel):
    id: uuid.UUID
    role: Role
    user: UserOut
    created_at: datetime


class MemberRoleUpdate(ApiModel):
    role: Role


class InvitationCreate(ApiModel):
    email: EmailStr
    role: Role = Role.MEMBER


class InvitationOut(ApiModel):
    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    created_at: datetime


class ApiKeyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str


class PlanOut(ApiModel):
    code: str
    name: str
    max_workflows: int
    max_runs_per_month: int
    max_concurrent_runs: int
    max_members: int


class LlmUsageOut(ApiModel):
    kind: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


class UsageOut(ApiModel):
    plan: PlanOut
    workflows: int
    runs_this_month: int
    members: int
    llm: list[LlmUsageOut]


class AuditLogOut(ApiModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    actor_api_key_id: uuid.UUID | None
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip_address: str | None
    created_at: datetime
