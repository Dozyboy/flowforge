from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from app.engine.nodes.base import NodeCategory, NodeContext, NodeResult, NodeType


class TriggerNode(NodeType):
    category: ClassVar[NodeCategory] = NodeCategory.TRIGGER

    async def execute(self, ctx: NodeContext) -> NodeResult:
        # The executor records the trigger payload directly; this is only used for previews.
        return NodeResult(output=ctx.run.trigger_payload)


class ManualTrigger(TriggerNode):
    type = "trigger_manual"
    label = "Manual"
    description = "Start the workflow from the dashboard or the API with a JSON payload."
    icon = "play"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "sample_payload": {
                "type": "object",
                "title": "Sample payload",
                "description": "Pre-filled when you click Test run.",
                "x-ui": "json",
            }
        },
        "additionalProperties": False,
    }


class WebhookTrigger(TriggerNode):
    type = "trigger_webhook"
    label = "Webhook"
    description = (
        "Start the workflow when an HTTP request arrives. Data is available as "
        "{{ trigger.body }}, {{ trigger.query }} and {{ trigger.headers }}."
    )
    icon = "webhook"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


class ScheduleTrigger(TriggerNode):
    type = "trigger_schedule"
    label = "Schedule"
    description = "Start the workflow on a cron schedule, e.g. 0 9 * * 1-5 for 9:00 on weekdays."
    icon = "clock"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "cron": {"type": "string", "title": "Cron expression", "default": "0 9 * * *"},
            "timezone": {"type": "string", "title": "Time zone", "default": "UTC"},
        },
        "required": ["cron", "timezone"],
        "additionalProperties": False,
    }

    def extra_validation(self, config: dict[str, Any]) -> list[str]:
        problems = []
        cron = config.get("cron")
        if isinstance(cron, str) and not croniter.is_valid(cron):
            problems.append("cron: not a valid cron expression")
        timezone = config.get("timezone")
        if isinstance(timezone, str):
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                problems.append(f"timezone: unknown time zone '{timezone}'")
        return problems


def next_cron_time(cron: str, timezone: str, after: datetime) -> datetime:
    """Next fire time in UTC for a cron expression evaluated in the given time zone."""
    local_after = after.astimezone(ZoneInfo(timezone))
    following: datetime = croniter(cron, local_after).get_next(datetime)
    return following.astimezone(ZoneInfo("UTC"))
