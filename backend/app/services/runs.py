import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, NotFoundError
from app.engine.executor import publish_run
from app.models import (
    Run,
    RunStatus,
    StepRun,
    StepStatus,
    TriggerType,
    Workflow,
    WorkflowVersion,
    Workspace,
)
from app.services import plans
from app.services.jobs import JobQueue

COPYABLE_STEP_STATUSES = (StepStatus.SUCCEEDED, StepStatus.SKIPPED)


@dataclass(frozen=True)
class RunPage:
    items: list[Run]
    total: int


async def start_run(
    session: AsyncSession,
    queue: JobQueue,
    workspace: Workspace,
    workflow: Workflow,
    *,
    trigger_type: TriggerType,
    payload: dict[str, Any],
    use_draft: bool = False,
    created_by_id: uuid.UUID | None = None,
) -> Run:
    """Create a run of the published version (or the draft, for test runs) and queue it."""
    await plans.ensure_can_start_run(session, workspace)
    version_id: uuid.UUID | None = None
    if use_draft:
        graph = workflow.draft_graph
    else:
        if workflow.published_version_id is None:
            raise AppError("Publish the workflow first, or use Test run to run the draft")
        version = await session.get(WorkflowVersion, workflow.published_version_id)
        if version is None:
            raise AppError("The published version is missing")
        graph, version_id = version.graph, version.id
    run = Run(
        workspace_id=workspace.id,
        workflow_id=workflow.id,
        version_id=version_id,
        graph=graph,
        status=RunStatus.QUEUED,
        trigger_type=trigger_type,
        trigger_payload=payload,
        created_by_id=created_by_id,
    )
    session.add(run)
    await session.commit()
    await queue.enqueue("execute_run", run_id=str(run.id))
    await publish_run(run)
    return run


async def list_runs(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID | None,
    status: RunStatus | None,
    limit: int,
    offset: int,
) -> RunPage:
    query = select(Run).where(Run.workspace_id == workspace_id, Run.parent_run_id.is_(None))
    if workflow_id:
        query = query.where(Run.workflow_id == workflow_id)
    if status:
        query = query.where(Run.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    items = await session.scalars(
        query.options(selectinload(Run.workflow))
        .order_by(Run.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return RunPage(items=list(items), total=int(total or 0))


async def get_run(session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await session.scalar(
        select(Run)
        .options(selectinload(Run.steps), selectinload(Run.workflow))
        .where(Run.id == run_id, Run.workspace_id == workspace_id)
    )
    if run is None:
        raise NotFoundError("Run not found")
    return run


async def child_runs(session: AsyncSession, run: Run) -> list[Run]:
    return list(
        await session.scalars(
            select(Run).where(Run.parent_run_id == run.id).order_by(Run.created_at)
        )
    )


async def cancel_run(session: AsyncSession, run: Run) -> Run:
    if RunStatus(run.status).is_terminal:
        raise AppError("This run has already finished")
    run.cancel_requested = True
    if run.status in (RunStatus.QUEUED, RunStatus.WAITING):
        # Nothing is executing it right now, so it can be finalised immediately.
        run.status = RunStatus.CANCELLED
        run.error = "Cancelled by a user"
        run.finished_at = datetime.now(UTC)
    await session.commit()
    await publish_run(run)
    return run


async def retry_run(
    session: AsyncSession,
    queue: JobQueue,
    workspace: Workspace,
    run: Run,
    *,
    from_failed_step: bool,
    created_by_id: uuid.UUID | None,
) -> Run:
    if run.status not in (RunStatus.FAILED, RunStatus.CANCELLED):
        raise AppError("Only failed or cancelled runs can be retried")
    await plans.ensure_can_start_run(session, workspace)
    retry = Run(
        workspace_id=run.workspace_id,
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        graph=run.graph,
        status=RunStatus.QUEUED,
        trigger_type=TriggerType.RETRY,
        trigger_payload=run.trigger_payload,
        retry_of_id=run.id,
        created_by_id=created_by_id,
    )
    session.add(retry)
    await session.flush()
    if from_failed_step:
        previous = await session.scalars(
            select(StepRun).where(
                StepRun.run_id == run.id, StepRun.status.in_(COPYABLE_STEP_STATUSES)
            )
        )
        for step in previous:
            session.add(
                StepRun(
                    run_id=retry.id,
                    workspace_id=step.workspace_id,
                    node_id=step.node_id,
                    node_type=step.node_type,
                    status=step.status,
                    attempt=step.attempt,
                    input=step.input,
                    output=step.output,
                    branch=step.branch,
                    started_at=step.started_at,
                    finished_at=step.finished_at,
                    duration_ms=step.duration_ms,
                )
            )
    await session.commit()
    await queue.enqueue("execute_run", run_id=str(retry.id))
    await publish_run(retry)
    return retry
