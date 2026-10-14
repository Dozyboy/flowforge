import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    ip_address: str | None = None


def record(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    actor: Actor,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the current transaction, so it commits with the change it records."""
    session.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            actor_api_key_id=actor.api_key_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            details=details or {},
            ip_address=actor.ip_address,
        )
    )


async def list_entries(
    session: AsyncSession, workspace_id: uuid.UUID, *, limit: int, offset: int
) -> list[AuditLog]:
    result = await session.scalars(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)
