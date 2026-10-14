import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import (
    AdminAccess,
    MemberAccess,
    MemberOrKeyAccess,
    QueueDep,
    SessionDep,
    ViewerAccess,
    ViewerOrKeyAccess,
)
from app.config import get_settings
from app.models import TriggerType, Workflow, WorkflowVersion
from app.schemas.run import RunSummaryOut
from app.schemas.workflow import (
    ActivateRequest,
    DiffOut,
    GraphIssueOut,
    ImportRequest,
    PublishRequest,
    PublishResultOut,
    SaveResultOut,
    SecretOut,
    TestRunRequest,
    VersionDetailOut,
    VersionOut,
    WorkflowCreate,
    WorkflowDetailOut,
    WorkflowOut,
    WorkflowSummaryOut,
    WorkflowUpdate,
)
from app.services import runs
from app.services import workflows as service

router = APIRouter(prefix="/workspaces/{workspace_id}/workflows", tags=["workflows"])


def webhook_url(workflow_id: uuid.UUID) -> str:
    return f"{get_settings().public_api_url}/api/v1/hooks/{workflow_id}"


def _out(workflow: Workflow) -> WorkflowOut:
    return WorkflowOut.model_validate(
        {
            **{c: getattr(workflow, c) for c in WorkflowOut.model_fields if hasattr(workflow, c)},
            "has_webhook_secret": workflow.webhook_secret_hash is not None,
        }
    )


async def _detail(session: SessionDep, workflow: Workflow) -> WorkflowDetailOut:
    published = (
        await session.get(WorkflowVersion, workflow.published_version_id)
        if workflow.published_version_id
        else None
    )
    return WorkflowDetailOut(
        **_out(workflow).model_dump(),
        issues=[GraphIssueOut(**i.as_dict()) for i in service.validate(workflow.draft_graph)],
        published_version=published.version if published else None,
        webhook_url=webhook_url(workflow.id),
    )


def run_summary(run: Any, workflow_name: str) -> RunSummaryOut:
    return RunSummaryOut(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_name=workflow_name,
        status=run.status,
        trigger_type=run.trigger_type,
        error=run.error,
        retry_of_id=run.retry_of_id,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.get("", response_model=list[WorkflowSummaryOut])
async def list_workflows(access: ViewerAccess, session: SessionDep) -> list[WorkflowSummaryOut]:
    return [
        WorkflowSummaryOut(
            id=s.workflow.id,
            name=s.workflow.name,
            description=s.workflow.description,
            is_active=s.workflow.is_active,
            trigger_type=s.trigger_type,
            published_version=s.published_version,
            last_run_status=s.last_run_status,
            last_run_at=s.last_run_at,
            runs_last_7_days=s.runs_last_7_days,
            updated_at=s.workflow.updated_at,
        )
        for s in await service.list_workflows(session, access.workspace_id)
    ]


@router.post("", response_model=WorkflowDetailOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreate, access: MemberAccess, session: SessionDep
) -> WorkflowDetailOut:
    if body.template_id:
        workflow = await service.create_from_template(
            session, access.workspace, access.actor, body.template_id
        )
    else:
        workflow = await service.create_workflow(
            session, access.workspace, access.actor, name=body.name, description=body.description
        )
    return await _detail(session, workflow)


@router.post("/import", response_model=WorkflowDetailOut, status_code=status.HTTP_201_CREATED)
async def import_workflow(
    body: ImportRequest, access: MemberAccess, session: SessionDep
) -> WorkflowDetailOut:
    workflow = await service.import_workflow(session, access.workspace, access.actor, body.data)
    return await _detail(session, workflow)


@router.get("/{workflow_id}", response_model=WorkflowDetailOut)
async def get_workflow(
    workflow_id: uuid.UUID, access: ViewerOrKeyAccess, session: SessionDep
) -> WorkflowDetailOut:
    return await _detail(
        session, await service.get_workflow(session, access.workspace_id, workflow_id)
    )


@router.patch("/{workflow_id}", response_model=SaveResultOut)
async def save_workflow(
    workflow_id: uuid.UUID, body: WorkflowUpdate, access: MemberAccess, session: SessionDep
) -> SaveResultOut:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    issues = await service.update_draft(
        session, workflow, name=body.name, description=body.description, graph=body.graph
    )
    return SaveResultOut(
        workflow=_out(workflow), issues=[GraphIssueOut(**i.as_dict()) for i in issues]
    )


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: uuid.UUID, access: AdminAccess, session: SessionDep) -> None:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    await service.delete_workflow(session, workflow, access.actor)


@router.post("/{workflow_id}/publish", response_model=PublishResultOut)
async def publish_workflow(
    workflow_id: uuid.UUID, body: PublishRequest, access: MemberAccess, session: SessionDep
) -> PublishResultOut:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    result = await service.publish(session, workflow, access.actor, body.note)
    return PublishResultOut(version=result.version.version, webhook_secret=result.webhook_secret)


@router.post("/{workflow_id}/activation", response_model=WorkflowOut)
async def set_activation(
    workflow_id: uuid.UUID, body: ActivateRequest, access: MemberAccess, session: SessionDep
) -> WorkflowOut:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    return _out(await service.set_active(session, workflow, body.active, access.actor))


@router.post("/{workflow_id}/webhook-secret", response_model=SecretOut)
async def rotate_secret(
    workflow_id: uuid.UUID, access: AdminAccess, session: SessionDep
) -> SecretOut:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    secret = await service.rotate_webhook_secret(session, workflow, access.actor)
    return SecretOut(webhook_secret=secret, webhook_url=webhook_url(workflow.id))


@router.get("/{workflow_id}/export")
async def export_workflow(
    workflow_id: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> dict[str, Any]:
    return service.export_workflow(
        await service.get_workflow(session, access.workspace_id, workflow_id)
    )


@router.post(
    "/{workflow_id}/runs", response_model=RunSummaryOut, status_code=status.HTTP_202_ACCEPTED
)
async def start_run(
    workflow_id: uuid.UUID,
    body: TestRunRequest,
    access: MemberOrKeyAccess,
    session: SessionDep,
    queue: QueueDep,
) -> RunSummaryOut:
    """Run the draft (test run) or the published version with a JSON payload."""
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    run = await runs.start_run(
        session,
        queue,
        access.workspace,
        workflow,
        trigger_type=TriggerType.MANUAL,
        payload=body.payload,
        use_draft=body.use_draft,
        created_by_id=access.user.id if access.user else None,
    )
    return run_summary(run, workflow.name)


@router.get("/{workflow_id}/versions", response_model=list[VersionOut])
async def list_versions(
    workflow_id: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> list[VersionOut]:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    return [VersionOut.model_validate(v) for v in await service.list_versions(session, workflow)]


@router.get("/{workflow_id}/versions/{version}", response_model=VersionDetailOut)
async def get_version(
    workflow_id: uuid.UUID, version: int, access: ViewerAccess, session: SessionDep
) -> VersionDetailOut:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    return VersionDetailOut.model_validate(await service.get_version(session, workflow, version))


@router.get("/{workflow_id}/versions/{version}/diff", response_model=DiffOut)
async def diff_version(
    workflow_id: uuid.UUID, version: int, access: ViewerAccess, session: SessionDep
) -> DiffOut:
    """Differences from this version to the current draft."""
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    old = await service.get_version(session, workflow, version)
    return DiffOut(**service.diff_graphs(old.graph, workflow.draft_graph))


@router.post("/{workflow_id}/versions/{version}/restore", response_model=WorkflowDetailOut)
async def restore_version(
    workflow_id: uuid.UUID, version: int, access: MemberAccess, session: SessionDep
) -> WorkflowDetailOut:
    workflow = await service.get_workflow(session, access.workspace_id, workflow_id)
    old = await service.get_version(session, workflow, version)
    await service.restore_version(session, workflow, old, access.actor)
    return await _detail(session, workflow)
