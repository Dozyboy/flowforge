"""Small builders for workflow graphs and runs in tests."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Run,
    RunStatus,
    StepRun,
    TriggerType,
    Workflow,
    WorkflowVersion,
    Workspace,
)


def node(
    node_id: str,
    node_type: str,
    config: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"label": node_id, "config": config or {}}
    if settings:
        data["settings"] = settings
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def edge(source: str, target: str, handle: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"id": f"{source}-{target}-{handle}", "source": source, "target": target}
    if handle is not None:
        data["sourceHandle"] = handle
    return data


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"nodes": nodes, "edges": edges}


async def make_workflow(
    session: AsyncSession,
    workspace: Workspace,
    workflow_graph: dict[str, Any],
    *,
    name: str = "Test workflow",
    publish: bool = False,
) -> Workflow:
    workflow = Workflow(workspace_id=workspace.id, name=name, draft_graph=workflow_graph)
    session.add(workflow)
    await session.flush()
    if publish:
        version = WorkflowVersion(
            workflow_id=workflow.id,
            workspace_id=workspace.id,
            version=1,
            graph=workflow_graph,
        )
        session.add(version)
        await session.flush()
        workflow.published_version_id = version.id
        workflow.is_active = True
    await session.commit()
    return workflow


async def make_run(
    session: AsyncSession,
    workflow: Workflow,
    payload: dict[str, Any] | None = None,
) -> Run:
    run = Run(
        workspace_id=workflow.workspace_id,
        workflow_id=workflow.id,
        graph=workflow.draft_graph,
        status=RunStatus.QUEUED,
        trigger_type=TriggerType.MANUAL,
        trigger_payload=payload or {},
    )
    session.add(run)
    await session.commit()
    return run


async def load_run(session: AsyncSession, run_id: uuid.UUID) -> tuple[Run, dict[str, StepRun]]:
    """Reload a run and its steps written by the executor's own sessions."""
    run = await session.get(Run, run_id, populate_existing=True)
    assert run is not None
    rows = await session.scalars(
        select(StepRun).where(StepRun.run_id == run_id).execution_options(populate_existing=True)
    )
    return run, {step.node_id: step for step in rows}
