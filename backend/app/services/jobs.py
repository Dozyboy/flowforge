"""Enqueueing background jobs.

Services depend on the `JobQueue` protocol rather than on arq directly, so tests can capture jobs
with `InMemoryJobQueue` and run them explicitly.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.config import get_settings


class JobQueue(Protocol):
    async def enqueue(self, job_name: str, **kwargs: Any) -> None: ...


class ArqJobQueue:
    def __init__(self) -> None:
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        return self._pool

    async def enqueue(self, job_name: str, **kwargs: Any) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(job_name, **kwargs)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


@dataclass
class InMemoryJobQueue:
    jobs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def enqueue(self, job_name: str, **kwargs: Any) -> None:
        self.jobs.append((job_name, kwargs))

    def named(self, job_name: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.jobs if name == job_name]


job_queue = ArqJobQueue()


def get_job_queue() -> JobQueue:
    return job_queue
