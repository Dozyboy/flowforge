import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Role
from app.core.security import generate_token, hash_token
from app.models import Invitation, Membership, User, Workspace
from app.services import audit, plans
from app.services import email as email_service
from app.services.audit import Actor
from app.services.jobs import JobQueue

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug[:48] or "workspace"


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name)
    slug = base
    while await session.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


async def create_workspace(session: AsyncSession, user: User, name: str) -> Workspace:
    workspace = Workspace(name=name.strip(), slug=await _unique_slug(session, name))
    session.add(workspace)
    await session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
    audit.record(
        session,
        workspace_id=workspace.id,
        actor=Actor(user_id=user.id),
        action="workspace.created",
        target_type="workspace",
        target_id=workspace.id,
    )
    await session.commit()
    return workspace


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    result = await session.scalars(
        select(Membership)
        .options(selectinload(Membership.workspace))
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at)
    )
    return list(result)


async def get_membership(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    return await session.scalar(
        select(Membership)
        .options(selectinload(Membership.workspace))
        .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    )


async def rename_workspace(
    session: AsyncSession, workspace: Workspace, actor: Actor, name: str
) -> Workspace:
    old_name = workspace.name
    workspace.name = name.strip()
    audit.record(
        session,
        workspace_id=workspace.id,
        actor=actor,
        action="workspace.renamed",
        target_type="workspace",
        target_id=workspace.id,
        details={"from": old_name, "to": workspace.name},
    )
    await session.commit()
    return workspace


async def delete_workspace(session: AsyncSession, workspace: Workspace) -> None:
    await session.delete(workspace)
    await session.commit()


# --- Members -------------------------------------------------------------------------------


async def list_members(session: AsyncSession, workspace_id: uuid.UUID) -> list[Membership]:
    result = await session.scalars(
        select(Membership)
        .options(selectinload(Membership.user))
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    )
    return list(result)


async def _get_member(
    session: AsyncSession, workspace_id: uuid.UUID, membership_id: uuid.UUID
) -> Membership:
    membership = await session.scalar(
        select(Membership)
        .options(selectinload(Membership.user))
        .where(Membership.id == membership_id, Membership.workspace_id == workspace_id)
    )
    if membership is None:
        raise NotFoundError("Member not found")
    return membership


async def _owner_count(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.role == Role.OWNER)
        )
        or 0
    )


def _ensure_can_manage(actor_role: Role, target_role: Role, new_role: Role | None = None) -> None:
    """Admins manage members and viewers; only owners can touch owners or grant ownership."""
    touches_owner = target_role == Role.OWNER or new_role == Role.OWNER
    if touches_owner and actor_role != Role.OWNER:
        raise PermissionDeniedError("Only owners can change or remove owners")
    if not actor_role.at_least(Role.ADMIN):
        raise PermissionDeniedError("Only admins can manage members")


async def change_member_role(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    new_role: Role,
    actor_role: Role,
    actor: Actor,
) -> Membership:
    membership = await _get_member(session, workspace_id, membership_id)
    _ensure_can_manage(actor_role, Role(membership.role), new_role)
    if (
        membership.role == Role.OWNER
        and new_role != Role.OWNER
        and await _owner_count(session, workspace_id) <= 1
    ):
        raise ConflictError("A workspace must have at least one owner")
    old_role = membership.role
    membership.role = new_role
    audit.record(
        session,
        workspace_id=workspace_id,
        actor=actor,
        action="member.role_changed",
        target_type="user",
        target_id=membership.user_id,
        details={"from": old_role, "to": new_role},
    )
    await session.commit()
    return membership


async def remove_member(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_role: Role,
    actor: Actor,
) -> None:
    membership = await _get_member(session, workspace_id, membership_id)
    is_self = membership.user_id == actor.user_id
    if not is_self:
        _ensure_can_manage(actor_role, Role(membership.role))
    if membership.role == Role.OWNER and await _owner_count(session, workspace_id) <= 1:
        raise ConflictError("A workspace must have at least one owner")
    audit.record(
        session,
        workspace_id=workspace_id,
        actor=actor,
        action="member.left" if is_self else "member.removed",
        target_type="user",
        target_id=membership.user_id,
    )
    await session.delete(membership)
    await session.commit()


# --- Invitations ---------------------------------------------------------------------------


async def list_invitations(session: AsyncSession, workspace_id: uuid.UUID) -> list[Invitation]:
    result = await session.scalars(
        select(Invitation)
        .where(
            Invitation.workspace_id == workspace_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
        .order_by(Invitation.created_at.desc())
    )
    return list(result)


async def invite(
    session: AsyncSession,
    queue: JobQueue,
    workspace: Workspace,
    inviter: User,
    actor_role: Role,
    *,
    email: str,
    role: Role,
) -> Invitation:
    email = email.strip().lower()
    if role == Role.OWNER and actor_role != Role.OWNER:
        raise PermissionDeniedError("Only owners can invite owners")
    await plans.ensure_can_add_member(session, workspace)
    already_member = await session.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace.id, User.email == email)
    )
    if already_member:
        raise ConflictError("This person is already a member")

    for pending in await list_invitations(session, workspace.id):
        if pending.email == email:
            pending.revoked_at = datetime.now(UTC)

    raw = generate_token(32)
    invitation = Invitation(
        workspace_id=workspace.id,
        email=email,
        role=role,
        token_hash=hash_token(raw),
        invited_by_id=inviter.id,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().invitation_ttl_days),
    )
    session.add(invitation)
    audit.record(
        session,
        workspace_id=workspace.id,
        actor=Actor(user_id=inviter.id),
        action="member.invited",
        target_type="invitation",
        details={"email": email, "role": role},
    )
    await session.commit()
    await email_service.queue_email(
        queue, email_service.invitation_email(email, workspace.name, inviter.full_name, raw)
    )
    return invitation


async def revoke_invitation(
    session: AsyncSession, workspace_id: uuid.UUID, invitation_id: uuid.UUID, actor: Actor
) -> None:
    invitation = await session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.workspace_id == workspace_id
        )
    )
    if invitation is None:
        raise NotFoundError("Invitation not found")
    invitation.revoked_at = datetime.now(UTC)
    audit.record(
        session,
        workspace_id=workspace_id,
        actor=actor,
        action="invitation.revoked",
        target_type="invitation",
        target_id=invitation.id,
    )
    await session.commit()


async def accept_invitation(session: AsyncSession, user: User, raw_token: str) -> Membership:
    invitation = await session.scalar(
        select(Invitation)
        .options(selectinload(Invitation.workspace))
        .where(Invitation.token_hash == hash_token(raw_token))
    )
    now = datetime.now(UTC)
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        raise AppError("This invitation is invalid or has expired")
    if invitation.email != user.email:
        raise PermissionDeniedError("This invitation was sent to a different email address")

    existing = await get_membership(session, invitation.workspace_id, user.id)
    if existing is not None:
        invitation.accepted_at = now
        await session.commit()
        return existing

    await plans.ensure_can_add_member(session, invitation.workspace)
    membership = Membership(
        workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role
    )
    session.add(membership)
    invitation.accepted_at = now
    if user.email_verified_at is None:
        # Receiving the invitation proves ownership of the address.
        user.email_verified_at = now
    audit.record(
        session,
        workspace_id=invitation.workspace_id,
        actor=Actor(user_id=user.id),
        action="member.joined",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    await session.refresh(membership, ["workspace"])
    return membership
