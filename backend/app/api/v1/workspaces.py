from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminAccess, CurrentUser, OwnerAccess, SessionDep, ViewerAccess
from app.core.permissions import Role
from app.schemas.auth import WorkspaceSummary
from app.schemas.run import DashboardOut, PendingApprovalOut
from app.schemas.workspace import (
    AuditLogOut,
    LlmUsageOut,
    PlanOut,
    UsageOut,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services import approvals, audit, dashboard, plans, usage
from app.services import workspaces as workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceSummary])
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceSummary]:
    memberships = await workspace_service.list_for_user(session, user.id)
    return [
        WorkspaceSummary(
            id=m.workspace.id,
            name=m.workspace.name,
            slug=m.workspace.slug,
            plan=m.workspace.plan,
            role=Role(m.role),
        )
        for m in memberships
    ]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate, user: CurrentUser, session: SessionDep
) -> WorkspaceOut:
    return WorkspaceOut.model_validate(
        await workspace_service.create_workspace(session, user, body.name)
    )


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(access: ViewerAccess) -> WorkspaceOut:
    return WorkspaceOut.model_validate(access.workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def rename_workspace(
    body: WorkspaceUpdate, access: AdminAccess, session: SessionDep
) -> WorkspaceOut:
    workspace = await workspace_service.rename_workspace(
        session, access.workspace, access.actor, body.name
    )
    return WorkspaceOut.model_validate(workspace)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(access: OwnerAccess, session: SessionDep) -> None:
    await workspace_service.delete_workspace(session, access.workspace)


@router.get("/{workspace_id}/usage", response_model=UsageOut)
async def get_usage(access: ViewerAccess, session: SessionDep) -> UsageOut:
    workspace = access.workspace
    return UsageOut(
        plan=PlanOut.model_validate(plans.plan_for(workspace)),
        workflows=await plans.count_workflows(session, workspace),
        runs_this_month=await plans.count_runs_this_month(session, workspace),
        members=await plans.count_members(session, workspace),
        llm=[
            LlmUsageOut.model_validate(row)
            for row in await usage.summarize(session, workspace.id, plans.month_start())
        ],
    )


@router.get("/{workspace_id}/dashboard", response_model=DashboardOut)
async def get_dashboard(
    access: ViewerAccess,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> DashboardOut:
    return DashboardOut.model_validate(await dashboard.build(session, access.workspace_id, days))


@router.get("/{workspace_id}/approvals", response_model=list[PendingApprovalOut])
async def pending_approvals(access: ViewerAccess, session: SessionDep) -> list[PendingApprovalOut]:
    return [
        PendingApprovalOut(
            id=a.id,
            run_id=a.run_id,
            workflow_name=a.run.workflow.name,
            node_id=a.node_id,
            message=a.message,
            approvers=a.approvers,
            expires_at=a.expires_at,
            created_at=a.created_at,
        )
        for a in await approvals.pending_for_workspace(session, access.workspace_id)
    ]


@router.get("/{workspace_id}/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    access: AdminAccess,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogOut]:
    entries = await audit.list_entries(session, access.workspace_id, limit=limit, offset=offset)
    return [AuditLogOut.model_validate(e) for e in entries]
