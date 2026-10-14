"""Scheduled triggers and housekeeping (see docs/adr/0007-scheduling-with-next-run-at.md)."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceededError
from app.engine.nodes.triggers import next_cron_time
from app.models import Run, RunStatus, TriggerType, Workflow, Workspace
from app.services import runs
from app.services.jobs import JobQueue

logger = structlog.get_logger(__name__)
BATCH_SIZE = 100


async def tick(session: AsyncSession, queue: JobQueue, now: datetime | None = None) -> int:
    """Start every due scheduled workflow once and move its next_run_at forward.

    Rows are locked with SKIP LOCKED, so several workers can tick at the same time without
    starting a workflow twice.
    """
    now = now or datetime.now(UTC)
    due = list(
        await session.scalars(
            select(Workflow)
            .where(
                Workflow.is_active.is_(True),
                Workflow.next_run_at.is_not(None),
                Workflow.next_run_at <= now,
            )
            .order_by(Workflow.next_run_at)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    )
    # Claim every due slot first: advancing next_run_at and committing releases the row locks
    # only after no other worker can see these slots as due any more.
    claimed: list[tuple[Workflow, datetime | None]] = []
    for workflow in due:
        claimed.append((workflow, workflow.next_run_at))
        if workflow.schedule_cron and workflow.schedule_timezone:
            workflow.next_run_at = next_cron_time(
                workflow.schedule_cron, workflow.schedule_timezone, now
            )
        else:
            workflow.next_run_at = None
    await session.commit()

    started = 0
    for workflow, scheduled_at in claimed:
        workspace = await session.get(Workspace, workflow.workspace_id)
        if workspace is None:
            continue
        try:
            await runs.start_run(
                session,
                queue,
                workspace,
                workflow,
                trigger_type=TriggerType.SCHEDULE,
                payload={"scheduled_at": scheduled_at.isoformat() if scheduled_at else None},
            )
            started += 1
        except QuotaExceededError:
            logger.warning("scheduled_run_skipped_quota", workflow_id=str(workflow.id))
    return started


async def fail_stuck_runs(session: AsyncSession, older_than: timedelta) -> int:
    """Runs left 'running' by a crashed worker are failed so they can be retried."""
    result = await session.execute(
        update(Run)
        .where(Run.status == RunStatus.RUNNING, Run.updated_at < datetime.now(UTC) - older_than)
        .values(
            status=RunStatus.FAILED,
            error="The worker stopped while running this workflow. Retry to continue.",
            finished_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
