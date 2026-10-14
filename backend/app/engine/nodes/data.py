from typing import Any, ClassVar

import structlog

from app.engine.nodes.base import NodeCategory, NodeContext, NodeResult, NodeType

logger = structlog.get_logger("workflow.log")


class TransformNode(NodeType):
    type = "transform"
    label = "Transform"
    description = "Build a new object from earlier data using {{ expressions }}."
    category: ClassVar[NodeCategory] = NodeCategory.DATA
    icon = "braces"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "output": {
                "title": "Output",
                "description": 'e.g. {"email": "{{ trigger.body.email | lower }}"}',
                "x-ui": "json",
            }
        },
        "required": ["output"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=ctx.config["output"])


class LogNode(NodeType):
    type = "log"
    label = "Log"
    description = "Write a message to the run log. Useful while building."
    category: ClassVar[NodeCategory] = NodeCategory.DATA
    icon = "scroll-text"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "title": "Message", "x-ui": "textarea", "minLength": 1},
            "level": {"enum": ["info", "warning", "error"], "title": "Level", "default": "info"},
        },
        "required": ["message"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        level = ctx.config.get("level", "info")
        getattr(logger, level)(
            "workflow_log",
            run_id=str(ctx.run.id),
            node_id=ctx.node.id,
            message=ctx.config["message"],
        )
        return NodeResult(output={"message": ctx.config["message"], "level": level})
