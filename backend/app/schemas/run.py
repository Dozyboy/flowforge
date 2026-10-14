import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.models import ApprovalStatus, RunStatus, StepStatus, TriggerType
from app.schemas.common import ApiModel


class RunSummaryOut(ApiModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    status: RunStatus
    trigger_type: TriggerType
    error: str | None
    retry_of_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class StepOut(ApiModel):
    id: uuid.UUID
    node_id: str
    node_type: str
    status: StepStatus
    attempt: int
    input: Any
    output: Any
    branch: str | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    resume_at: datetime | None


class ChildRunOut(ApiModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: RunStatus
    error: str | None
    trigger_payload: dict[str, Any]


class RunDetailOut(RunSummaryOut):
    version_id: uuid.UUID | None
    graph: dict[str, Any]
    trigger_payload: dict[str, Any]
    cancel_requested: bool
    steps: list[StepOut]
    children: list[ChildRunOut]


class RetryRequest(ApiModel):
    from_failed_step: bool = True


class WebhookAccepted(ApiModel):
    run_id: uuid.UUID
    status: RunStatus
    duplicate: bool


class ApprovalPublicOut(ApiModel):
    workflow_name: str
    message: str
    status: ApprovalStatus
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    run_status: RunStatus


class ApprovalDecision(ApiModel):
    decision: str = Field(pattern="^(approve|reject)$")
    name: str | None = Field(default=None, max_length=320)
    comment: str | None = Field(default=None, max_length=2000)


class PendingApprovalOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    workflow_name: str
    node_id: str
    message: str
    approvers: list[str]
    expires_at: datetime
    created_at: datetime


class DailyRunsOut(ApiModel):
    day: date
    succeeded: int
    failed: int
    other: int


class FailingWorkflowOut(ApiModel):
    workflow_id: uuid.UUID
    name: str
    failures: int


class DashboardOut(ApiModel):
    period_days: int
    total_runs: int
    succeeded: int
    failed: int
    success_rate: float | None
    median_duration_seconds: float | None
    active_workflows: int
    pending_approvals: int
    ai_cost_usd: Decimal
    daily: list[DailyRunsOut]
    failing_workflows: list[FailingWorkflowOut]
