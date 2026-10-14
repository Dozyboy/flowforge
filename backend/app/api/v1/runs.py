import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import MemberAccess, QueueDep, SessionDep, ViewerOrKeyAccess
from app.api.v1.workflows import run_summary
from app.models import RunStatus
from app.schemas.common import Page
from app.schemas.run import ChildRunOut, RetryRequest, RunDetailOut, RunSummaryOut, StepOut
from app.services import runs

router = APIRouter(prefix="/workspaces/{workspace_id}/runs", tags=["runs"])


@router.get("", response_model=Page[RunSummaryOut])
async def list_runs(
    access: ViewerOrKeyAccess,
    session: SessionDep,
    workflow_id: uuid.UUID | None = None,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RunSummaryOut]:
    page = await runs.list_runs(
        session,
        access.workspace_id,
        workflow_id=workflow_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[run_summary(r, r.workflow.name) for r in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: uuid.UUID, access: ViewerOrKeyAccess, session: SessionDep
) -> RunDetailOut:
    run = await runs.get_run(session, access.workspace_id, run_id)
    summary = run_summary(run, run.workflow.name)
    return RunDetailOut(
        **summary.model_dump(),
        version_id=run.version_id,
        graph=run.graph,
        trigger_payload=run.trigger_payload,
        cancel_requested=run.cancel_requested,
        steps=[StepOut.model_validate(s) for s in run.steps],
        children=[ChildRunOut.model_validate(c) for c in await runs.child_runs(session, run)],
    )


@router.post("/{run_id}/cancel", response_model=RunSummaryOut)
async def cancel_run(run_id: uuid.UUID, access: MemberAccess, session: SessionDep) -> RunSummaryOut:
    run = await runs.get_run(session, access.workspace_id, run_id)
    await runs.cancel_run(session, run)
    return run_summary(run, run.workflow.name)


@router.post("/{run_id}/retry", response_model=RunSummaryOut, status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run_id: uuid.UUID,
    body: RetryRequest,
    access: MemberAccess,
    session: SessionDep,
    queue: QueueDep,
) -> RunSummaryOut:
    run = await runs.get_run(session, access.workspace_id, run_id)
    retry = await runs.retry_run(
        session,
        queue,
        access.workspace,
        run,
        from_failed_step=body.from_failed_step,
        created_by_id=access.require_user().id,
    )
    return run_summary(retry, run.workflow.name)
