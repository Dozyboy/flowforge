from app.engine.nodes import ai, data, integrations, logic, triggers
from app.engine.nodes.base import NodeType


class NodeRegistry:
    def __init__(self, node_types: list[NodeType]) -> None:
        self._types = {node_type.type: node_type for node_type in node_types}

    def get(self, type_name: str) -> NodeType | None:
        return self._types.get(type_name)

    def all(self) -> list[NodeType]:
        return list(self._types.values())


registry = NodeRegistry(
    [
        triggers.ManualTrigger(),
        triggers.WebhookTrigger(),
        triggers.ScheduleTrigger(),
        ai.SummarizeNode(),
        ai.ClassifyNode(),
        ai.ExtractNode(),
        ai.GenerateNode(),
        ai.AgentNode(),
        logic.ConditionNode(),
        logic.SwitchNode(),
        logic.MergeNode(),
        logic.DelayNode(),
        logic.ApprovalNode(),
        logic.SubWorkflowNode(),
        logic.ForEachNode(),
        data.TransformNode(),
        data.LogNode(),
        integrations.HttpRequestNode(),
        integrations.SendEmailNode(),
        integrations.SlackMessageNode(),
        integrations.TelegramMessageNode(),
        integrations.GoogleSheetsAppendNode(),
    ]
)
