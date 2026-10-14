import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models import RunStatus
from app.schemas.common import ApiModel


class GraphIssueOut(ApiModel):
    node_id: str | None
    message: str


class WorkflowCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    template_id: str | None = Field(default=None, max_length=100)


class WorkflowUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    graph: dict[str, Any] | None = None


class WorkflowSummaryOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    is_active: bool
    trigger_type: str | None
    published_version: int | None
    last_run_status: RunStatus | None
    last_run_at: datetime | None
    runs_last_7_days: int
    updated_at: datetime


class WorkflowOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    draft_graph: dict[str, Any]
    is_active: bool
    published_version_id: uuid.UUID | None
    has_webhook_secret: bool
    schedule_cron: str | None
    schedule_timezone: str | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowDetailOut(WorkflowOut):
    issues: list[GraphIssueOut]
    published_version: int | None
    webhook_url: str


class SaveResultOut(ApiModel):
    workflow: WorkflowOut
    issues: list[GraphIssueOut]


class PublishRequest(ApiModel):
    note: str = Field(default="", max_length=300)


class PublishResultOut(ApiModel):
    version: int
    webhook_secret: str | None = Field(
        description="Returned only when a new webhook secret was created. Store it now."
    )


class ActivateRequest(ApiModel):
    active: bool


class SecretOut(ApiModel):
    webhook_secret: str
    webhook_url: str


class VersionOut(ApiModel):
    id: uuid.UUID
    version: int
    note: str
    created_by_id: uuid.UUID | None
    created_at: datetime


class VersionDetailOut(VersionOut):
    graph: dict[str, Any]


class DiffOut(ApiModel):
    added_nodes: list[str]
    removed_nodes: list[str]
    changed_nodes: list[dict[str, Any]]
    added_edges: list[str]
    removed_edges: list[str]


class TestRunRequest(ApiModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    use_draft: bool = True


class ImportRequest(ApiModel):
    data: dict[str, Any]


class TemplateOut(ApiModel):
    id: str
    name: str
    description: str
    category: str
    graph: dict[str, Any]


class NodeTypeOut(ApiModel):
    type: str
    label: str
    category: str
    description: str
    icon: str
    config_schema: dict[str, Any]
    static_handles: list[str]
    dynamic_handles_key: str | None
    dynamic_handles_extra: list[str]
