import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.security import generate_api_key, hash_token
from app.models import ApiKey, Workspace
from app.services import audit
from app.services.audit import Actor


async def create(
    session: AsyncSession, workspace_id: uuid.UUID, name: str, actor: Actor
) -> tuple[ApiKey, str]:
    raw, prefix = generate_api_key()
    api_key = ApiKey(
        workspace_id=workspace_id,
        name=name.strip(),
        prefix=prefix,
        key_hash=hash_token(raw),
        created_by_id=actor.user_id,
    )
    session.add(api_key)
    await session.flush()
    audit.record(
        session,
        workspace_id=workspace_id,
        actor=actor,
        action="api_key.created",
        target_type="api_key",
        target_id=api_key.id,
        details={"name": api_key.name},
    )
    await session.commit()
    return api_key, raw


async def list_active(session: AsyncSession, workspace_id: uuid.UUID) -> list[ApiKey]:
    result = await session.scalars(
        select(ApiKey)
        .where(ApiKey.workspace_id == workspace_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    return list(result)


async def revoke(
    session: AsyncSession, workspace_id: uuid.UUID, api_key_id: uuid.UUID, actor: Actor
) -> None:
    api_key = await session.scalar(
        select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.workspace_id == workspace_id)
    )
    if api_key is None or api_key.revoked_at is not None:
        raise NotFoundError("API key not found")
    api_key.revoked_at = datetime.now(UTC)
    audit.record(
        session,
        workspace_id=workspace_id,
        actor=actor,
        action="api_key.revoked",
        target_type="api_key",
        target_id=api_key.id,
    )
    await session.commit()


async def authenticate(session: AsyncSession, raw_key: str) -> tuple[ApiKey, Workspace] | None:
    row = (
        await session.execute(
            select(ApiKey, Workspace)
            .join(Workspace, Workspace.id == ApiKey.workspace_id)
            .where(ApiKey.key_hash == hash_token(raw_key), ApiKey.revoked_at.is_(None))
        )
    ).first()
    if row is None:
        return None
    api_key, workspace = row
    api_key.last_used_at = datetime.now(UTC)
    await session.commit()
    return api_key, workspace
