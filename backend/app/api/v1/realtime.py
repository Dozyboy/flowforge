import asyncio
import contextlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import NotFoundError
from app.core.realtime import hub, issue_ws_ticket, redeem_ws_ticket, workspace_channel
from app.services import workspaces

router = APIRouter(tags=["realtime"])

PING_INTERVAL_SECONDS = 25


class TicketRequest(BaseModel):
    workspace_id: uuid.UUID


class TicketOut(BaseModel):
    ticket: str


@router.post("/ws-tickets", response_model=TicketOut)
async def create_ticket(body: TicketRequest, user: CurrentUser, session: SessionDep) -> TicketOut:
    """One-time ticket for the WebSocket, so access tokens never appear in URLs."""
    if await workspaces.get_membership(session, body.workspace_id, user.id) is None:
        raise NotFoundError("Workspace not found")
    ticket = await issue_ws_ticket(
        {"user_id": str(user.id), "workspace_id": str(body.workspace_id)}
    )
    return TicketOut(ticket=ticket)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: Annotated[str, Query()]) -> None:
    claims = await redeem_ws_ticket(ticket)
    if not claims:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    channels = [workspace_channel(uuid.UUID(claims["workspace_id"]))]
    await websocket.accept()
    hub.add(websocket, channels)

    async def keepalive() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            await websocket.send_text('{"type":"ping"}')

    pinger = asyncio.create_task(keepalive())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pinger.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pinger
        hub.remove(websocket, channels)
