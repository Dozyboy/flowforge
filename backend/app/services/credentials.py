import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_json
from app.core.errors import AppError, ConflictError, NotFoundError
from app.engine.credential_types import CREDENTIAL_TYPES
from app.models import Credential
from app.services import audit
from app.services.audit import Actor


def _validated(type_name: str, data: dict[str, str]) -> dict[str, str]:
    credential_type = CREDENTIAL_TYPES.get(type_name)
    if credential_type is None:
        raise AppError(f"Unknown credential type '{type_name}'")
    allowed = {f.name for f in credential_type.fields}
    cleaned = {k: v.strip() for k, v in data.items() if k in allowed and isinstance(v, str)}
    problems = credential_type.validate(cleaned)
    if problems:
        raise AppError("; ".join(problems))
    return cleaned


async def list_credentials(session: AsyncSession, workspace_id: uuid.UUID) -> list[Credential]:
    return list(
        await session.scalars(
            select(Credential)
            .where(Credential.workspace_id == workspace_id)
            .order_by(Credential.name)
        )
    )


async def get_credential(
    session: AsyncSession, workspace_id: uuid.UUID, credential_id: uuid.UUID
) -> Credential:
    credential = await session.scalar(
        select(Credential).where(
            Credential.id == credential_id, Credential.workspace_id == workspace_id
        )
    )
    if credential is None:
        raise NotFoundError("Credential not found")
    return credential


async def create_credential(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor: Actor,
    *,
    name: str,
    type_name: str,
    data: dict[str, str],
) -> Credential:
    credential = Credential(
        workspace_id=workspace_id,
        name=name.strip(),
        type=type_name,
        encrypted_data=encrypt_json(_validated(type_name, data)),
        created_by_id=actor.user_id,
    )
    session.add(credential)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A credential with this name already exists") from exc
    audit.record(
        session,
        workspace_id=workspace_id,
        actor=actor,
        action="credential.created",
        target_type="credential",
        target_id=credential.id,
        details={"name": credential.name, "type": type_name},
    )
    await session.commit()
    return credential


async def update_credential(
    session: AsyncSession,
    credential: Credential,
    actor: Actor,
    *,
    name: str | None,
    data: dict[str, str] | None,
) -> Credential:
    if name is not None:
        credential.name = name.strip()
    if data is not None:
        credential.encrypted_data = encrypt_json(_validated(credential.type, data))
    audit.record(
        session,
        workspace_id=credential.workspace_id,
        actor=actor,
        action="credential.updated",
        target_type="credential",
        target_id=credential.id,
        details={"name": credential.name, "secret_replaced": data is not None},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A credential with this name already exists") from exc
    return credential


async def delete_credential(session: AsyncSession, credential: Credential, actor: Actor) -> None:
    audit.record(
        session,
        workspace_id=credential.workspace_id,
        actor=actor,
        action="credential.deleted",
        target_type="credential",
        target_id=credential.id,
        details={"name": credential.name},
    )
    await session.delete(credential)
    await session.commit()
