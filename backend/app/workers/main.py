"""arq worker: `arq app.workers.main.WorkerSettings`."""

import uuid
from datetime import timedelta
from typing import Any, ClassVar

import httpx
import structlog
from arq import cron
from arq.connections import RedisSettings
from prometheus_client import start_http_server

from app.config import get_settings
from app.core.llm import get_llm_client
from app.core.logging import configure_logging
from app.core.redis import close_redis
from app.db.session import dispose_engine, get_session_factory
from app.engine.executor import EngineDeps, RunExecutor
from app.services import approvals, scheduler
from app.services import email as email_service
from app.services.jobs import job_queue

logger = structlog.get_logger(__name__)

Context = dict[str, Any]


async def startup(ctx: Context) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "development")
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    ctx["http"] = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0), headers={"User-Agent": f"{settings.app_name}/1.0"}
    )
    ctx["executor"] = RunExecutor(
        EngineDeps(
            session_factory=get_session_factory(),
            llm=get_llm_client(),
            http=ctx["http"],
            queue=job_queue,
        ),
        lock_ttl_seconds=settings.run_job_timeout_seconds,
    )


async def shutdown(ctx: Context) -> None:
    await ctx["http"].aclose()
    await job_queue.close()
    await close_redis()
    await dispose_engine()


async def execute_run(ctx: Context, run_id: str) -> str:
    executor: RunExecutor = ctx["executor"]
    return await executor.execute(uuid.UUID(run_id))


async def send_email(ctx: Context, to: str, subject: str, text: str, html_body: str) -> None:
    await email_service.deliver(to, subject, text, html_body)
    logger.info("email_sent", subject=subject)


async def schedule_tick(ctx: Context) -> None:
    async with get_session_factory()() as session:
        started = await scheduler.tick(session, job_queue)
    if started:
        logger.info("scheduled_runs_started", count=started)


async def housekeeping(ctx: Context) -> None:
    async with get_session_factory()() as session:
        expired = await approvals.expire_overdue(session, job_queue)
        stuck = await scheduler.fail_stuck_runs(
            session, timedelta(seconds=get_settings().run_job_timeout_seconds * 2)
        )
    if expired or stuck:
        logger.info("housekeeping", expired_approvals=expired, failed_stuck_runs=stuck)


class WorkerSettings:
    functions: ClassVar = [execute_run, send_email]
    cron_jobs: ClassVar = [
        cron(schedule_tick, second={0}),
        cron(housekeeping, minute=set(range(0, 60, 5)), second={30}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 20
    job_timeout = get_settings().run_job_timeout_seconds
    max_tries = 3
