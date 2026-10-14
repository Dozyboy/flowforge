import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminAccess, SessionDep
from app.schemas.workspace import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services import api_keys

router = APIRouter(prefix="/workspaces/{workspace_id}/api-keys", tags=["api keys"])


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(access: AdminAccess, session: SessionDep) -> list[ApiKeyOut]:
    keys = await api_keys.list_active(session, access.workspace_id)
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate, access: AdminAccess, session: SessionDep
) -> ApiKeyCreated:
    api_key, raw = await api_keys.create(session, access.workspace_id, body.name, access.actor)
    return ApiKeyCreated(**ApiKeyOut.model_validate(api_key).model_dump(), key=raw)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(api_key_id: uuid.UUID, access: AdminAccess, session: SessionDep) -> None:
    await api_keys.revoke(session, access.workspace_id, api_key_id, access.actor)
