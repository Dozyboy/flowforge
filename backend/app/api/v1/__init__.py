from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    auth,
    credentials,
    members,
    meta,
    public,
    realtime,
    runs,
    workflows,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1")
for module in (
    auth,
    workspaces,
    members,
    api_keys,
    workflows,
    runs,
    credentials,
    meta,
    public,
    realtime,
):
    api_router.include_router(module.router)
