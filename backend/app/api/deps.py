"""Shared FastAPI dependencies: database session, authentication and workspace access."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, NotFoundError, PermissionDeniedError
from app.core.llm import LLMClient, get_llm_client
from app.core.permissions import Role
from app.core.rate_limit import client_ip, hit
from app.core.security import API_KEY_PREFIX, decode_access_token
from app.db.session import get_db
from app.models import ApiKey, User, Workspace
from app.services import api_keys, workspaces
from app.services.audit import Actor
from app.services.jobs import JobQueue, get_job_queue

SessionDep = Annotated[AsyncSession, Depends(get_db)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]

API_KEY_RATE_LIMIT = 600  # requests per minute per key


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def get_current_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> User:
    token = _bearer_token(authorization)
    if token is None or token.startswith(API_KEY_PREFIX):
        raise AuthenticationError("Authentication required")
    user_id = decode_access_token(token)
    if user_id is None:
        raise AuthenticationError("Invalid or expired access token")
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not active")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class WorkspaceAccess:
    """The workspace a request operates on and who is acting on it."""

    workspace: Workspace
    role: Role
    actor: Actor
    user: User | None = None
    api_key: ApiKey | None = None

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    def require_user(self) -> User:
        if self.user is None:
            raise PermissionDeniedError("This action requires a user session, not an API key")
        return self.user


def require_workspace_role(
    minimum: Role, *, allow_api_key: bool = False
) -> Callable[..., Awaitable[WorkspaceAccess]]:
    async def dependency(
        request: Request,
        session: SessionDep,
        workspace_id: Annotated[uuid.UUID, Path()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> WorkspaceAccess:
        token = _bearer_token(authorization)
        if token is None:
            raise AuthenticationError("Authentication required")
        ip = client_ip(request)

        if token.startswith(API_KEY_PREFIX):
            if not allow_api_key:
                raise PermissionDeniedError("API keys cannot access this endpoint")
            result = await api_keys.authenticate(session, token)
            if result is None or result[1].id != workspace_id:
                raise AuthenticationError("Invalid API key")
            api_key, workspace = result
            await hit(f"api_key:{api_key.id}", API_KEY_RATE_LIMIT, 60)
            role = Role.MEMBER
            if not role.at_least(minimum):
                raise PermissionDeniedError("API keys cannot perform this action")
            return WorkspaceAccess(
                workspace=workspace,
                role=role,
                actor=Actor(api_key_id=api_key.id, ip_address=ip),
                api_key=api_key,
            )

        user = await get_current_user(session, authorization)
        membership = await workspaces.get_membership(session, workspace_id, user.id)
        if membership is None:
            # 404 rather than 403, so workspace IDs cannot be probed.
            raise NotFoundError("Workspace not found")
        role = Role(membership.role)
        if not role.at_least(minimum):
            raise PermissionDeniedError(f"This action requires the {minimum} role or higher")
        return WorkspaceAccess(
            workspace=membership.workspace,
            role=role,
            actor=Actor(user_id=user.id, ip_address=ip),
            user=user,
        )

    return dependency


ViewerAccess = Annotated[WorkspaceAccess, Depends(require_workspace_role(Role.VIEWER))]
MemberAccess = Annotated[WorkspaceAccess, Depends(require_workspace_role(Role.MEMBER))]
AdminAccess = Annotated[WorkspaceAccess, Depends(require_workspace_role(Role.ADMIN))]
OwnerAccess = Annotated[WorkspaceAccess, Depends(require_workspace_role(Role.OWNER))]
ViewerOrKeyAccess = Annotated[
    WorkspaceAccess, Depends(require_workspace_role(Role.VIEWER, allow_api_key=True))
]
MemberOrKeyAccess = Annotated[
    WorkspaceAccess, Depends(require_workspace_role(Role.MEMBER, allow_api_key=True))
]
