import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceededError
from app.models import Membership, Run, RunStatus, Workflow, Workspace


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    max_workflows: int
    max_runs_per_month: int
    max_concurrent_runs: int
    max_members: int


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 5, 1_000, 2, 2),
    "pro": Plan("pro", "Pro", 100, 50_000, 10, 20),
}


def plan_for(workspace: Workspace) -> Plan:
    return PLANS.get(workspace.plan, PLANS["free"])


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _count(session: AsyncSession, query: Select[Any]) -> int:
    return int(await session.scalar(query) or 0)


async def count_workflows(session: AsyncSession, workspace: Workspace) -> int:
    return await _count(
        session,
        select(func.count()).select_from(Workflow).where(Workflow.workspace_id == workspace.id),
    )


async def count_runs_this_month(session: AsyncSession, workspace: Workspace) -> int:
    return await _count(
        session,
        select(func.count())
        .select_from(Run)
        .where(
            Run.workspace_id == workspace.id,
            Run.parent_run_id.is_(None),
            Run.created_at >= month_start(),
        ),
    )


async def count_running(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    return await _count(
        session,
        select(func.count())
        .select_from(Run)
        .where(
            Run.workspace_id == workspace_id,
            Run.parent_run_id.is_(None),
            Run.status == RunStatus.RUNNING,
        ),
    )


async def count_members(session: AsyncSession, workspace: Workspace) -> int:
    return await _count(
        session,
        select(func.count()).select_from(Membership).where(Membership.workspace_id == workspace.id),
    )


async def ensure_can_add_workflow(session: AsyncSession, workspace: Workspace) -> None:
    plan = plan_for(workspace)
    if await count_workflows(session, workspace) >= plan.max_workflows:
        raise QuotaExceededError(
            f"The {plan.name} plan allows {plan.max_workflows} workflows. Upgrade to add more."
        )


async def ensure_can_start_run(session: AsyncSession, workspace: Workspace) -> None:
    plan = plan_for(workspace)
    if await count_runs_this_month(session, workspace) >= plan.max_runs_per_month:
        raise QuotaExceededError(
            f"The {plan.name} plan allows {plan.max_runs_per_month} runs per month."
        )


async def ensure_can_add_member(session: AsyncSession, workspace: Workspace) -> None:
    plan = plan_for(workspace)
    if await count_members(session, workspace) >= plan.max_members:
        raise QuotaExceededError(
            f"The {plan.name} plan allows {plan.max_members} members. Upgrade to invite more."
        )
