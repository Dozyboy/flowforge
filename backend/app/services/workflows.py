import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.security import generate_token, hash_token
from app.engine.graph import Graph, GraphError, GraphIssue, validate_graph
from app.engine.nodes.registry import registry
from app.engine.nodes.triggers import next_cron_time
from app.models import Run, RunStatus, Workflow, WorkflowVersion, Workspace
from app.models.workflow import EMPTY_GRAPH
from app.services import audit, plans
from app.services.audit import Actor

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
EXPORT_FORMAT = "flowforge.workflow/v1"


class WorkflowValidationError(AppError):
    code = "workflow_invalid"

    def __init__(self, issues: list[GraphIssue]) -> None:
        super().__init__(
            "The workflow has problems that must be fixed before publishing",
            extra={"issues": [issue.as_dict() for issue in issues]},
        )


@dataclass(frozen=True)
class WorkflowSummary:
    workflow: Workflow
    published_version: int | None
    trigger_type: str | None
    last_run_status: RunStatus | None
    last_run_at: datetime | None
    runs_last_7_days: int


@dataclass(frozen=True)
class PublishResult:
    version: WorkflowVersion
    webhook_secret: str | None


def trigger_type_of(graph: dict[str, Any]) -> str | None:
    try:
        return Graph.parse(graph).trigger().type
    except GraphError:
        return None


def validate(graph: dict[str, Any]) -> list[GraphIssue]:
    return validate_graph(graph, registry)


async def get_workflow(
    session: AsyncSession, workspace_id: uuid.UUID, workflow_id: uuid.UUID
) -> Workflow:
    workflow = await session.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id)
    )
    if workflow is None:
        raise NotFoundError("Workflow not found")
    return workflow


async def list_workflows(session: AsyncSession, workspace_id: uuid.UUID) -> list[WorkflowSummary]:
    workflows = list(
        await session.scalars(
            select(Workflow)
            .where(Workflow.workspace_id == workspace_id)
            .order_by(Workflow.updated_at.desc())
        )
    )
    if not workflows:
        return []
    ids = [w.id for w in workflows]
    versions = dict(
        (
            await session.execute(
                select(WorkflowVersion.id, WorkflowVersion.version).where(
                    WorkflowVersion.workflow_id.in_(ids)
                )
            )
        ).all()
    )
    last_runs: dict[uuid.UUID, tuple[RunStatus, datetime]] = {}
    latest = (
        select(Run.workflow_id, Run.status, Run.created_at)
        .where(Run.workflow_id.in_(ids), Run.parent_run_id.is_(None))
        .distinct(Run.workflow_id)
        .order_by(Run.workflow_id, Run.created_at.desc())
    )
    for workflow_id, status, created_at in (await session.execute(latest)).all():
        last_runs[workflow_id] = (status, created_at)
    week_ago = datetime.now(UTC) - timedelta(days=7)
    counts = dict(
        (
            await session.execute(
                select(Run.workflow_id, func.count())
                .where(
                    Run.workflow_id.in_(ids),
                    Run.parent_run_id.is_(None),
                    Run.created_at >= week_ago,
                )
                .group_by(Run.workflow_id)
            )
        ).all()
    )
    return [
        WorkflowSummary(
            workflow=w,
            published_version=versions.get(w.published_version_id)
            if w.published_version_id
            else None,
            trigger_type=trigger_type_of(w.draft_graph),
            last_run_status=last_runs.get(w.id, (None, None))[0],
            last_run_at=last_runs.get(w.id, (None, None))[1],
            runs_last_7_days=int(counts.get(w.id, 0)),
        )
        for w in workflows
    ]


async def create_workflow(
    session: AsyncSession,
    workspace: Workspace,
    actor: Actor,
    *,
    name: str,
    description: str = "",
    graph: dict[str, Any] | None = None,
) -> Workflow:
    await plans.ensure_can_add_workflow(session, workspace)
    if graph is not None:
        try:
            Graph.parse(graph)
        except GraphError as exc:
            raise AppError(f"Invalid workflow graph: {exc}") from exc
    workflow = Workflow(
        workspace_id=workspace.id,
        name=name.strip(),
        description=description.strip(),
        draft_graph=graph or dict(EMPTY_GRAPH),
        created_by_id=actor.user_id,
    )
    session.add(workflow)
    await session.flush()
    audit.record(
        session,
        workspace_id=workspace.id,
        actor=actor,
        action="workflow.created",
        target_type="workflow",
        target_id=workflow.id,
        details={"name": workflow.name},
    )
    await session.commit()
    return workflow


async def update_draft(
    session: AsyncSession,
    workflow: Workflow,
    *,
    name: str | None,
    description: str | None,
    graph: dict[str, Any] | None,
) -> list[GraphIssue]:
    """Save whatever the user has (drafts may be incomplete); return the issues found."""
    if name is not None:
        workflow.name = name.strip()
    if description is not None:
        workflow.description = description.strip()
    if graph is not None:
        try:
            Graph.parse(graph)
        except GraphError as exc:
            raise AppError(f"Invalid workflow graph: {exc}") from exc
        workflow.draft_graph = graph
    await session.commit()
    return validate(workflow.draft_graph)


async def delete_workflow(session: AsyncSession, workflow: Workflow, actor: Actor) -> None:
    audit.record(
        session,
        workspace_id=workflow.workspace_id,
        actor=actor,
        action="workflow.deleted",
        target_type="workflow",
        target_id=workflow.id,
        details={"name": workflow.name},
    )
    await session.delete(workflow)
    await session.commit()


def _apply_trigger_settings(workflow: Workflow, graph: dict[str, Any]) -> str | None:
    """Configure scheduling and webhook secret from the published trigger.

    Returns a new plain webhook secret when one had to be created.
    """
    trigger = Graph.parse(graph).trigger()
    new_secret = None
    if trigger.type == "trigger_schedule":
        workflow.schedule_cron = str(trigger.config["cron"])
        workflow.schedule_timezone = str(trigger.config.get("timezone", "UTC"))
        workflow.next_run_at = next_cron_time(
            workflow.schedule_cron, workflow.schedule_timezone, datetime.now(UTC)
        )
    else:
        workflow.schedule_cron = workflow.schedule_timezone = None
        workflow.next_run_at = None
    if trigger.type == "trigger_webhook" and workflow.webhook_secret_hash is None:
        new_secret = generate_token(24)
        workflow.webhook_secret_hash = hash_token(new_secret)
    return new_secret


async def publish(
    session: AsyncSession, workflow: Workflow, actor: Actor, note: str = ""
) -> PublishResult:
    issues = validate(workflow.draft_graph)
    if issues:
        raise WorkflowValidationError(issues)
    latest = await session.scalar(
        select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow.id)
    )
    version = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=workflow.workspace_id,
        version=int(latest or 0) + 1,
        graph=workflow.draft_graph,
        note=note.strip()[:300],
        created_by_id=actor.user_id,
    )
    session.add(version)
    await session.flush()
    workflow.published_version_id = version.id
    workflow.is_active = True
    secret = _apply_trigger_settings(workflow, version.graph)
    audit.record(
        session,
        workspace_id=workflow.workspace_id,
        actor=actor,
        action="workflow.published",
        target_type="workflow",
        target_id=workflow.id,
        details={"version": version.version},
    )
    await session.commit()
    return PublishResult(version=version, webhook_secret=secret)


async def set_active(
    session: AsyncSession, workflow: Workflow, active: bool, actor: Actor
) -> Workflow:
    if active and workflow.published_version_id is None:
        raise AppError("Publish the workflow before activating it")
    workflow.is_active = active
    if active and workflow.schedule_cron and workflow.schedule_timezone:
        workflow.next_run_at = next_cron_time(
            workflow.schedule_cron, workflow.schedule_timezone, datetime.now(UTC)
        )
    audit.record(
        session,
        workspace_id=workflow.workspace_id,
        actor=actor,
        action="workflow.activated" if active else "workflow.paused",
        target_type="workflow",
        target_id=workflow.id,
    )
    await session.commit()
    return workflow


async def rotate_webhook_secret(session: AsyncSession, workflow: Workflow, actor: Actor) -> str:
    secret = generate_token(24)
    workflow.webhook_secret_hash = hash_token(secret)
    audit.record(
        session,
        workspace_id=workflow.workspace_id,
        actor=actor,
        action="workflow.webhook_secret_rotated",
        target_type="workflow",
        target_id=workflow.id,
    )
    await session.commit()
    return secret


# --- versions ------------------------------------------------------------------------------


async def list_versions(session: AsyncSession, workflow: Workflow) -> list[WorkflowVersion]:
    return list(
        await session.scalars(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow.id)
            .order_by(WorkflowVersion.version.desc())
        )
    )


async def get_version(
    session: AsyncSession, workflow: Workflow, version_number: int
) -> WorkflowVersion:
    version = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.version == version_number
        )
    )
    if version is None:
        raise NotFoundError("Version not found")
    return version


def diff_graphs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Node and edge level differences, ignoring canvas positions."""
    old_nodes = {n["id"]: n for n in old.get("nodes", [])}
    new_nodes = {n["id"]: n for n in new.get("nodes", [])}

    def comparable(n: dict[str, Any]) -> dict[str, Any]:
        return {"type": n.get("type"), "data": n.get("data", {})}

    changed = []
    for node_id in sorted(old_nodes.keys() & new_nodes.keys()):
        before, after = comparable(old_nodes[node_id]), comparable(new_nodes[node_id])
        if before != after:
            fields = sorted(
                key
                for key in set(before["data"].get("config", {}))
                | set(after["data"].get("config", {}))
                if before["data"].get("config", {}).get(key)
                != after["data"].get("config", {}).get(key)
            )
            changed.append({"node_id": node_id, "config_fields": fields})

    def edge_key(e: dict[str, Any]) -> str:
        return f"{e.get('source')}->{e.get('target')}:{e.get('sourceHandle') or ''}"

    old_edges = {edge_key(e) for e in old.get("edges", [])}
    new_edges = {edge_key(e) for e in new.get("edges", [])}
    return {
        "added_nodes": sorted(new_nodes.keys() - old_nodes.keys()),
        "removed_nodes": sorted(old_nodes.keys() - new_nodes.keys()),
        "changed_nodes": changed,
        "added_edges": sorted(new_edges - old_edges),
        "removed_edges": sorted(old_edges - new_edges),
    }


async def restore_version(
    session: AsyncSession, workflow: Workflow, version: WorkflowVersion, actor: Actor
) -> Workflow:
    workflow.draft_graph = version.graph
    audit.record(
        session,
        workspace_id=workflow.workspace_id,
        actor=actor,
        action="workflow.version_restored",
        target_type="workflow",
        target_id=workflow.id,
        details={"version": version.version},
    )
    await session.commit()
    return workflow


# --- import / export / templates -----------------------------------------------------------


def export_workflow(workflow: Workflow) -> dict[str, Any]:
    return {
        "format": EXPORT_FORMAT,
        "name": workflow.name,
        "description": workflow.description,
        "graph": workflow.draft_graph,
    }


async def import_workflow(
    session: AsyncSession, workspace: Workspace, actor: Actor, data: dict[str, Any]
) -> Workflow:
    if data.get("format") != EXPORT_FORMAT or not isinstance(data.get("graph"), dict):
        raise AppError(f"Not a FlowForge export (expected format {EXPORT_FORMAT})")
    return await create_workflow(
        session,
        workspace,
        actor,
        name=str(data.get("name") or "Imported workflow")[:120],
        description=str(data.get("description") or ""),
        graph=data["graph"],
    )


def list_templates() -> list[dict[str, Any]]:
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        templates.append({"id": path.stem, **data})
    return templates


async def create_from_template(
    session: AsyncSession, workspace: Workspace, actor: Actor, template_id: str
) -> Workflow:
    template = next((t for t in list_templates() if t["id"] == template_id), None)
    if template is None:
        raise NotFoundError("Template not found")
    return await create_workflow(
        session,
        workspace,
        actor,
        name=template["name"],
        description=template["description"],
        graph=template["graph"],
    )
