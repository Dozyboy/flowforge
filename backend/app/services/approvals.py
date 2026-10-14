from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, NotFoundError
from app.core.security import hash_token
from app.models import Approval, ApprovalStatus, Run, RunStatus, Workflow
from app.services.jobs import JobQueue


@dataclass(frozen=True)
class ApprovalView:
    approval: Approval
    workflow_name: str
    run_status: RunStatus


async def _by_token(session: AsyncSession, token: str) -> Approval:
    approval = await session.scalar(
        select(Approval)
        .options(selectinload(Approval.run))
        .where(Approval.token_hash == hash_token(token))
    )
    if approval is None:
        raise NotFoundError("This approval link is not valid")
    return approval


async def view(session: AsyncSession, token: str) -> ApprovalView:
    approval = await _by_token(session, token)
    if approval.status == ApprovalStatus.PENDING and approval.expires_at <= datetime.now(UTC):
        approval.status = ApprovalStatus.EXPIRED
        await session.commit()
    workflow = await session.get(Workflow, approval.run.workflow_id)
    return ApprovalView(
        approval=approval,
        workflow_name=workflow.name if workflow else "Deleted workflow",
        run_status=RunStatus(approval.run.status),
    )


async def decide(
    session: AsyncSession,
    queue: JobQueue,
    token: str,
    *,
    approve: bool,
    decided_by: str | None,
    comment: str | None,
) -> Approval:
    approval = await _by_token(session, token)
    now = datetime.now(UTC)
    if approval.status != ApprovalStatus.PENDING:
        raise AppError(f"This request was already {approval.status}")
    if approval.expires_at <= now:
        approval.status = ApprovalStatus.EXPIRED
        await session.commit()
        await queue.enqueue("execute_run", run_id=str(approval.run_id))
        raise AppError("This approval link has expired")
    if approval.run.status != RunStatus.WAITING:
        raise AppError("The run is no longer waiting for a decision")
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_at = now
    approval.decided_by = (decided_by or "").strip()[:320] or None
    approval.comment = (comment or "").strip()[:2000] or None
    await session.commit()
    await queue.enqueue("execute_run", run_id=str(approval.run_id))
    return approval


async def expire_overdue(session: AsyncSession, queue: JobQueue) -> int:
    """Expire pending approvals past their deadline and wake their runs (→ 'rejected' branch)."""
    rows = (
        await session.execute(
            update(Approval)
            .where(
                Approval.status == ApprovalStatus.PENDING,
                Approval.expires_at <= datetime.now(UTC),
            )
            .values(status=ApprovalStatus.EXPIRED)
            .returning(Approval.run_id)
        )
    ).all()
    await session.commit()
    for (run_id,) in rows:
        await queue.enqueue("execute_run", run_id=str(run_id))
    return len(rows)


async def pending_for_workspace(session: AsyncSession, workspace_id: object) -> list[Approval]:
    return list(
        await session.scalars(
            select(Approval)
            .options(selectinload(Approval.run).selectinload(Run.workflow))
            .where(Approval.workspace_id == workspace_id, Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.desc())
        )
    )
