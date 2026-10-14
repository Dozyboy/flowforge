import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminAccess, SessionDep, ViewerAccess
from app.schemas.credential import CredentialCreate, CredentialOut, CredentialUpdate
from app.services import credentials as service

router = APIRouter(prefix="/workspaces/{workspace_id}/credentials", tags=["credentials"])


@router.get("", response_model=list[CredentialOut])
async def list_credentials(access: ViewerAccess, session: SessionDep) -> list[CredentialOut]:
    return [
        CredentialOut.model_validate(c)
        for c in await service.list_credentials(session, access.workspace_id)
    ]


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreate, access: AdminAccess, session: SessionDep
) -> CredentialOut:
    credential = await service.create_credential(
        session,
        access.workspace_id,
        access.actor,
        name=body.name,
        type_name=body.type,
        data=body.data,
    )
    return CredentialOut.model_validate(credential)


@router.patch("/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: uuid.UUID, body: CredentialUpdate, access: AdminAccess, session: SessionDep
) -> CredentialOut:
    credential = await service.get_credential(session, access.workspace_id, credential_id)
    updated = await service.update_credential(
        session, credential, access.actor, name=body.name, data=body.data
    )
    return CredentialOut.model_validate(updated)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID, access: AdminAccess, session: SessionDep
) -> None:
    credential = await service.get_credential(session, access.workspace_id, credential_id)
    await service.delete_credential(session, credential, access.actor)
