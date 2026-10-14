"""Real-time events: Redis pub/sub fan-out to WebSocket clients.

Every process publishes to Redis. Each API process runs one listener that pattern-subscribes to
all event channels and forwards each message to the WebSocket clients it holds for that channel.
Subscribing to patterns once (instead of per channel) keeps the listener simple and avoids
issuing subscribe commands concurrently with the read loop.
"""

import asyncio
import contextlib
import json
import uuid
from typing import Any

import structlog
from fastapi import WebSocket

from app.core.redis import get_redis
from app.core.security import generate_token

logger = structlog.get_logger(__name__)

CHANNEL_PATTERNS = ("workspace:*",)
WS_TICKET_TTL_SECONDS = 30


def workspace_channel(workspace_id: uuid.UUID) -> str:
    return f"workspace:{workspace_id}"


async def publish(channel: str, event_type: str, data: dict[str, Any]) -> None:
    payload = json.dumps({"type": event_type, "data": data}, default=str)
    await get_redis().publish(channel, payload)


async def issue_ws_ticket(claims: dict[str, str]) -> str:
    ticket = generate_token(24)
    await get_redis().set(f"ws_ticket:{ticket}", json.dumps(claims), ex=WS_TICKET_TTL_SECONDS)
    return ticket


async def redeem_ws_ticket(ticket: str) -> dict[str, str] | None:
    raw = await get_redis().getdel(f"ws_ticket:{ticket}")
    return json.loads(raw) if raw else None


class RealtimeHub:
    def __init__(self) -> None:
        self._clients: dict[str, set[WebSocket]] = {}
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen(), name="realtime-listener")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def add(self, websocket: WebSocket, channels: list[str]) -> None:
        for channel in channels:
            self._clients.setdefault(channel, set()).add(websocket)

    def remove(self, websocket: WebSocket, channels: list[str]) -> None:
        for channel in channels:
            clients = self._clients.get(channel)
            if clients is None:
                continue
            clients.discard(websocket)
            if not clients:
                del self._clients[channel]

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = get_redis().pubsub()
                await pubsub.psubscribe(*CHANNEL_PATTERNS)
                async for message in pubsub.listen():
                    if message.get("type") == "pmessage":
                        await self._dispatch(message["channel"], message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("realtime_listener_failed")
                await asyncio.sleep(1)

    async def _dispatch(self, channel: str, data: str) -> None:
        for websocket in list(self._clients.get(channel, ())):
            try:
                await websocket.send_text(data)
            except Exception:
                logger.info("realtime_send_failed", channel=channel)


hub = RealtimeHub()
