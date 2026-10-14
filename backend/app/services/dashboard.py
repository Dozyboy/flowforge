import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approval, ApprovalStatus, LlmUsage, Run, RunStatus, Workflow


@dataclass(frozen=True)
class DailyRuns:
    day: date
    succeeded: int
    failed: int
    other: int


@dataclass(frozen=True)
class FailingWorkflow:
    workflow_id: uuid.UUID
    name: str
    failures: int


@dataclass(frozen=True)
class Dashboard:
    period_days: int
    total_runs: int
    succeeded: int
    failed: int
    success_rate: float | None
    median_duration_seconds: float | None
    active_workflows: int
    pending_approvals: int
    ai_cost_usd: Decimal
    daily: list[DailyRuns]
    failing_workflows: list[FailingWorkflow]


async def build(session: AsyncSession, workspace_id: uuid.UUID, days: int) -> Dashboard:
    since = datetime.now(UTC) - timedelta(days=days)
    top_level = (
        Run.workspace_id == workspace_id,
        Run.parent_run_id.is_(None),
        Run.created_at >= since,
    )

    total, succeeded, failed, median = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Run.status == RunStatus.SUCCEEDED),
                func.count().filter(Run.status == RunStatus.FAILED),
                func.percentile_cont(0.5).within_group(
                    func.extract("epoch", Run.finished_at - Run.started_at)
                ),
            ).where(*top_level)
        )
    ).one()

    day = cast(Run.created_at, Date)
    rows = await session.execute(
        select(
            day,
            func.sum(case((Run.status == RunStatus.SUCCEEDED, 1), else_=0)),
            func.sum(case((Run.status == RunStatus.FAILED, 1), else_=0)),
            func.count(),
        )
        .where(*top_level)
        .group_by(day)
        .order_by(day)
    )
    by_day = {r[0]: (int(r[1] or 0), int(r[2] or 0), int(r[3])) for r in rows}
    daily = []
    for offset in range(days + 1):
        d = since.date() + timedelta(days=offset)
        ok, bad, count = by_day.get(d, (0, 0, 0))
        daily.append(DailyRuns(day=d, succeeded=ok, failed=bad, other=count - ok - bad))

    failing = await session.execute(
        select(Run.workflow_id, Workflow.name, func.count())
        .join(Workflow, Workflow.id == Run.workflow_id)
        .where(*top_level, Run.status == RunStatus.FAILED)
        .group_by(Run.workflow_id, Workflow.name)
        .order_by(func.count().desc())
        .limit(5)
    )

    active = await session.scalar(
        select(func.count())
        .select_from(Workflow)
        .where(Workflow.workspace_id == workspace_id, Workflow.is_active.is_(True))
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(Approval)
        .where(Approval.workspace_id == workspace_id, Approval.status == ApprovalStatus.PENDING)
    )
    cost = await session.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.workspace_id == workspace_id, LlmUsage.created_at >= since
        )
    )
    finished = int(succeeded) + int(failed)
    return Dashboard(
        period_days=days,
        total_runs=int(total),
        succeeded=int(succeeded),
        failed=int(failed),
        success_rate=round(int(succeeded) / finished, 4) if finished else None,
        median_duration_seconds=round(float(median), 2) if median is not None else None,
        active_workflows=int(active or 0),
        pending_approvals=int(pending or 0),
        ai_cost_usd=Decimal(cost or 0),
        daily=daily,
        failing_workflows=[FailingWorkflow(wid, name, int(n)) for wid, name, n in failing.all()],
    )
