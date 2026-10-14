import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from app.core.security import generate_token, hash_token
from app.engine.nodes.base import (
    NodeCategory,
    NodeContext,
    NodeExecutionError,
    NodeResult,
    NodeType,
    Wait,
    require_list,
)
from app.models import Approval, ApprovalStatus
from app.services import email as email_service

if TYPE_CHECKING:
    from app.models import StepRun

OPERATORS = [
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "greater_than",
    "less_than",
    "is_empty",
    "is_not_empty",
    "matches_regex",
]


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "is_empty":
        return _is_empty(left)
    if operator == "is_not_empty":
        return not _is_empty(left)
    if operator in ("greater_than", "less_than"):
        a, b = _as_number(left), _as_number(right)
        if a is None or b is None:
            raise NodeExecutionError(
                f"'{operator}' needs two numbers, got {left!r} and {right!r}", retryable=False
            )
        return a > b if operator == "greater_than" else a < b
    if operator in ("equals", "not_equals"):
        a, b = _as_number(left), _as_number(right)
        equal = a == b if a is not None and b is not None else str(left) == str(right)
        return equal if operator == "equals" else not equal
    if operator in ("contains", "not_contains"):
        container = left if isinstance(left, list | dict) else str(left)
        found = (
            right in container if isinstance(container, list | dict) else str(right) in container
        )
        return found if operator == "contains" else not found
    if operator == "matches_regex":
        try:
            return re.search(str(right), str(left)) is not None
        except re.error as exc:
            raise NodeExecutionError(f"Invalid regular expression: {exc}", retryable=False) from exc
    raise NodeExecutionError(f"Unknown operator '{operator}'", retryable=False)


class LogicNode(NodeType):
    category: ClassVar[NodeCategory] = NodeCategory.LOGIC


class ConditionNode(LogicNode):
    type = "condition"
    label = "If / else"
    description = "Route to 'true' or 'false' by comparing two values."
    icon = "split"
    static_handles: ClassVar[list[str]] = ["true", "false"]
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "left": {"type": "string", "title": "Value", "minLength": 1},
            "operator": {"enum": OPERATORS, "title": "Operator", "default": "equals"},
            "right": {"type": "string", "title": "Compare with", "default": ""},
        },
        "required": ["left", "operator"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        left, right = ctx.config.get("left"), ctx.config.get("right", "")
        result = compare(left, ctx.config["operator"], right)
        return NodeResult(
            output={"result": result, "left": left, "right": right},
            branch="true" if result else "false",
        )


class SwitchNode(LogicNode):
    type = "switch"
    label = "Switch"
    description = "Route to the output whose name equals the value, or to 'default'."
    icon = "git-fork"
    dynamic_handles_key: ClassVar[str | None] = "cases"
    dynamic_handles_extra: ClassVar[list[str]] = ["default"]
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "value": {"type": "string", "title": "Value", "minLength": 1},
            "cases": {
                "type": "array",
                "title": "Cases",
                "items": {"type": "string", "minLength": 1, "not": {"const": "default"}},
                "minItems": 1,
                "maxItems": 20,
                "uniqueItems": True,
                "x-ui": "tags",
            },
        },
        "required": ["value", "cases"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        value = str(ctx.config["value"])
        matched = value if value in ctx.config["cases"] else "default"
        return NodeResult(output={"value": value, "matched": matched}, branch=matched)


class MergeNode(LogicNode):
    type = "merge"
    label = "Merge"
    description = "Wait for all incoming branches and combine their outputs by step id."
    icon = "merge"

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=dict(ctx.parent_outputs))


class DelayNode(LogicNode):
    type = "delay"
    label = "Delay"
    description = "Pause the run, then continue. The worker is free while waiting."
    icon = "hourglass"
    pausable: ClassVar[bool] = True
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "integer",
                "title": "Seconds",
                "minimum": 1,
                "maximum": 7 * 24 * 3600,
                "default": 60,
            }
        },
        "required": ["seconds"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        resume_at = datetime.now(UTC) + timedelta(seconds=int(ctx.config["seconds"]))
        return NodeResult(wait=Wait(resume_at=resume_at, output={"resume_at": resume_at}))

    async def resume(self, ctx: NodeContext, step: "StepRun") -> NodeResult | None:
        if step.resume_at and datetime.now(UTC) >= step.resume_at:
            return NodeResult(output={"waited_seconds": ctx.config.get("seconds")})
        return None


class ApprovalNode(LogicNode):
    type = "approval"
    label = "Human approval"
    description = "Email approvers a link and wait. Continues on 'approved' or 'rejected'."
    icon = "user-check"
    pausable: ClassVar[bool] = True
    static_handles: ClassVar[list[str]] = ["approved", "rejected"]
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "approvers": {
                "type": "array",
                "title": "Approver emails",
                "items": {"type": "string", "minLength": 3},
                "minItems": 1,
                "maxItems": 10,
                "x-ui": "tags",
            },
            "message": {
                "type": "string",
                "title": "Message to approvers",
                "x-ui": "textarea",
                "minLength": 1,
            },
            "expires_in_hours": {
                "type": "integer",
                "title": "Expires after (hours)",
                "minimum": 1,
                "maximum": 720,
                "default": 72,
            },
        },
        "required": ["approvers", "message"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        approvers = [
            str(a).strip().lower() for a in require_list(ctx.config["approvers"], "approvers")
        ]
        token = generate_token(32)
        expires_at = datetime.now(UTC) + timedelta(
            hours=int(ctx.config.get("expires_in_hours", 72))
        )
        approval = Approval(
            workspace_id=ctx.run.workspace_id,
            run_id=ctx.run.id,
            node_id=ctx.node.id,
            token_hash=hash_token(token),
            approvers=approvers,
            message=str(ctx.config["message"]),
            expires_at=expires_at,
        )
        ctx.session.add(approval)
        await ctx.session.commit()
        for approver in approvers:
            await email_service.queue_email(
                ctx.queue,
                email_service.approval_email(approver, ctx.workflow_name, approval.message, token),
            )
        return NodeResult(
            wait=Wait(output={"approval_id": str(approval.id), "expires_at": expires_at})
        )

    async def resume(self, ctx: NodeContext, step: "StepRun") -> NodeResult | None:
        approval = await ctx.session.scalar(
            select(Approval)
            .where(Approval.run_id == ctx.run.id, Approval.node_id == ctx.node.id)
            .order_by(Approval.created_at.desc())
        )
        if approval is None or approval.status == ApprovalStatus.PENDING:
            return None
        approved = approval.status == ApprovalStatus.APPROVED
        return NodeResult(
            output={
                "approved": approved,
                "status": approval.status,
                "decided_by": approval.decided_by,
                "comment": approval.comment,
            },
            branch="approved" if approved else "rejected",
        )


WORKFLOW_FIELD = {"type": "string", "title": "Workflow", "x-ui": "workflow", "format": "uuid"}


def _workflow_id(ctx: NodeContext) -> uuid.UUID:
    try:
        return uuid.UUID(str(ctx.config["workflow_id"]))
    except ValueError as exc:
        raise NodeExecutionError("Choose a valid workflow", retryable=False) from exc


class SubWorkflowNode(LogicNode):
    type = "sub_workflow"
    label = "Run workflow"
    description = "Run another workflow's published version and use its result."
    icon = "workflow"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "workflow_id": WORKFLOW_FIELD,
            "input": {"title": "Input", "description": "Passed as {{ trigger }}", "x-ui": "json"},
        },
        "required": ["workflow_id"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        payload = ctx.config.get("input") or {}
        result = await ctx.run_child(_workflow_id(ctx), {"input": payload})
        return NodeResult(output={"result": result})


class ForEachNode(LogicNode):
    type = "for_each"
    label = "For each"
    description = (
        "Run another workflow once per item of a list. Each run sees {{ trigger.item }} "
        "and {{ trigger.index }}."
    )
    icon = "repeat"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "items": {"type": "string", "title": "Items (expression)", "minLength": 1},
            "workflow_id": WORKFLOW_FIELD,
            "concurrency": {
                "type": "integer",
                "title": "Parallel runs",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
            },
            "max_items": {
                "type": "integer",
                "title": "Max items",
                "minimum": 1,
                "maximum": 100,
                "default": 100,
            },
        },
        "required": ["items", "workflow_id"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        items = require_list(ctx.config["items"], "items")
        limit = int(ctx.config.get("max_items", 100))
        if len(items) > limit:
            raise NodeExecutionError(
                f"{len(items)} items exceed the limit of {limit}", retryable=False
            )
        workflow_id = _workflow_id(ctx)
        semaphore = asyncio.Semaphore(int(ctx.config.get("concurrency", 3)))

        async def run_one(index: int, item: Any) -> dict[str, Any]:
            async with semaphore:
                return await ctx.run_child(workflow_id, {"item": item, "index": index})

        results = await asyncio.gather(*(run_one(i, item) for i, item in enumerate(items)))
        return NodeResult(output={"results": list(results), "count": len(results)})
