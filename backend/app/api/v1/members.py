import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminAccess, CurrentUser, QueueDep, SessionDep, ViewerAccess
from app.schemas.auth import TokenRequest, WorkspaceSummary
from app.schemas.workspace import InvitationCreate, InvitationOut, MemberOut, MemberRoleUpdate
from app.services import workspaces as workspace_service

router = APIRouter(tags=["members"])


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(access: ViewerAccess, session: SessionDep) -> list[MemberOut]:
    members = await workspace_service.list_members(session, access.workspace_id)
    return [MemberOut.model_validate(m) for m in members]


@router.patch("/workspaces/{workspace_id}/members/{membership_id}", response_model=MemberOut)
async def change_role(
    membership_id: uuid.UUID, body: MemberRoleUpdate, access: AdminAccess, session: SessionDep
) -> MemberOut:
    membership = await workspace_service.change_member_role(
        session, access.workspace_id, membership_id, body.role, access.role, access.actor
    )
    return MemberOut.model_validate(membership)


@router.delete(
    "/workspaces/{workspace_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    membership_id: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> None:
    await workspace_service.remove_member(
        session, access.workspace_id, membership_id, access.role, access.actor
    )


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(access: AdminAccess, session: SessionDep) -> list[InvitationOut]:
    invitations = await workspace_service.list_invitations(session, access.workspace_id)
    return [InvitationOut.model_validate(i) for i in invitations]


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite(
    body: InvitationCreate, access: AdminAccess, session: SessionDep, queue: QueueDep
) -> InvitationOut:
    invitation = await workspace_service.invite(
        session,
        queue,
        access.workspace,
        access.require_user(),
        access.role,
        email=body.email,
        role=body.role,
    )
    return InvitationOut.model_validate(invitation)


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: uuid.UUID, access: AdminAccess, session: SessionDep
) -> None:
    await workspace_service.revoke_invitation(
        session, access.workspace_id, invitation_id, access.actor
    )


@router.post("/invitations/accept", response_model=WorkspaceSummary)
async def accept_invitation(
    body: TokenRequest, user: CurrentUser, session: SessionDep
) -> WorkspaceSummary:
    membership = await workspace_service.accept_invitation(session, user, body.token)
    return WorkspaceSummary(
        id=membership.workspace.id,
        name=membership.workspace.name,
        slug=membership.workspace.slug,
        plan=membership.workspace.plan,
        role=membership.role,
    )
