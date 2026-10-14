"""Fixed-window rate limiting backed by Redis.

A fixed window (INCR + EXPIRE) allows up to 2x the limit across a window boundary. That is an
accepted trade-off here: it is one round trip, needs no Lua script, and the limits only protect
against abuse rather than enforce billing.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request

from app.config import get_settings
from app.core.errors import RateLimitedError
from app.core.redis import get_redis


async def hit(key: str, limit: int, window_seconds: int) -> None:
    if not get_settings().rate_limit_enabled:
        return
    window = int(time.time()) // window_seconds
    redis_key = f"rl:{key}:{window}"
    redis = get_redis()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds)
        count, _ = await pipe.execute()
    if int(count) > limit:
        retry_after = window_seconds - int(time.time()) % window_seconds
        raise RateLimitedError(
            "Too many requests, please slow down", extra={"retry_after": retry_after}
        )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit_by_ip(
    group: str, limit: int, window_seconds: int
) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        await hit(f"{group}:ip:{client_ip(request)}", limit, window_seconds)

    return dependency
