import json
from typing import Any, ClassVar

from app.core.errors import ServiceUnavailableError
from app.core.llm import ChatMessage, render_prompt
from app.engine.nodes.base import (
    NodeCategory,
    NodeContext,
    NodeExecutionError,
    NodeResult,
    NodeType,
)
from app.engine.nodes.http_tools import call_http_tool, tool_definitions

TEXT_FIELD = {"type": "string", "title": "Text", "x-ui": "textarea", "minLength": 1}
INSTRUCTIONS_FIELD = {
    "type": "string",
    "title": "Extra instructions",
    "x-ui": "textarea",
    "default": "",
}


class AINode(NodeType):
    category: ClassVar[NodeCategory] = NodeCategory.AI
    icon = "sparkles"

    async def _complete(
        self, ctx: NodeContext, messages: list[ChatMessage], *, json_mode: bool = False
    ) -> str:
        try:
            completion = await ctx.llm.complete(messages, json_mode=json_mode, temperature=0.1)
        except ServiceUnavailableError as exc:
            raise NodeExecutionError(exc.detail) from exc
        ctx.record_usage(self.type, completion.usage)
        return completion.text.strip()

    async def _complete_json(self, ctx: NodeContext, prompt: str) -> dict[str, Any]:
        text = await self._complete(ctx, [{"role": "user", "content": prompt}], json_mode=True)
        try:
            data = json.loads(text.removeprefix("```json").removesuffix("```").strip())
        except json.JSONDecodeError as exc:
            raise NodeExecutionError("The model did not return valid JSON") from exc
        if not isinstance(data, dict):
            raise NodeExecutionError("The model did not return a JSON object")
        return data


class SummarizeNode(AINode):
    type = "ai_summarize"
    label = "AI summarize"
    description = "Summarize text in a few words or sentences."
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "text": TEXT_FIELD,
            "max_words": {
                "type": "integer",
                "title": "Max words",
                "minimum": 5,
                "maximum": 500,
                "default": 80,
            },
            "instructions": INSTRUCTIONS_FIELD,
        },
        "required": ["text"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        prompt = render_prompt(
            "summarize_v1",
            text=ctx.config["text"],
            max_words=ctx.config.get("max_words", 80),
            instructions=ctx.config.get("instructions", ""),
        )
        summary = await self._complete(ctx, [{"role": "user", "content": prompt}])
        return NodeResult(output={"summary": summary})


class ClassifyNode(AINode):
    type = "ai_classify"
    label = "AI classify"
    description = "Pick one label for the text. Each label is a separate output you can route on."
    dynamic_handles_key: ClassVar[str | None] = "labels"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "text": TEXT_FIELD,
            "labels": {
                "type": "array",
                "title": "Labels",
                "items": {"type": "string", "minLength": 1, "maxLength": 50},
                "minItems": 2,
                "maxItems": 10,
                "uniqueItems": True,
                "x-ui": "tags",
            },
            "instructions": INSTRUCTIONS_FIELD,
        },
        "required": ["text", "labels"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        labels: list[str] = ctx.config["labels"]
        data = await self._complete_json(
            ctx,
            render_prompt(
                "classify_v1",
                text=ctx.config["text"],
                labels="\n".join(f"- {label}" for label in labels),
                instructions=ctx.config.get("instructions", ""),
            ),
        )
        returned = str(data.get("label", "")).strip()
        label = next((lbl for lbl in labels if lbl.lower() == returned.lower()), None)
        if label is None:
            raise NodeExecutionError(f"The model returned an unknown label '{returned}'")
        return NodeResult(output={"label": label, "reason": data.get("reason", "")}, branch=label)


class ExtractNode(AINode):
    type = "ai_extract"
    label = "AI extract"
    description = "Pull structured fields out of free text (emails, forms, documents)."
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "text": TEXT_FIELD,
            "fields": {
                "type": "object",
                "title": "Fields",
                "description": 'Field name → description, e.g. {"company": "Company name"}',
                "minProperties": 1,
                "maxProperties": 30,
                "additionalProperties": {"type": "string"},
                "x-ui": "json",
            },
        },
        "required": ["text", "fields"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        fields: dict[str, str] = ctx.config["fields"]
        data = await self._complete_json(
            ctx,
            render_prompt(
                "extract_v1",
                text=ctx.config["text"],
                fields=json.dumps(fields, ensure_ascii=False, indent=2),
            ),
        )
        return NodeResult(output={name: data.get(name) for name in fields})


class GenerateNode(AINode):
    type = "ai_generate"
    label = "AI generate"
    description = "Write text from a prompt: replies, descriptions, translations."
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "title": "Prompt", "x-ui": "textarea", "minLength": 1},
            "system": {
                "type": "string",
                "title": "System instructions",
                "x-ui": "textarea",
                "default": "",
            },
        },
        "required": ["prompt"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        messages: list[ChatMessage] = []
        if ctx.config.get("system"):
            messages.append({"role": "system", "content": ctx.config["system"]})
        messages.append(
            {"role": "user", "content": render_prompt("generate_v1", prompt=ctx.config["prompt"])}
        )
        return NodeResult(output={"text": await self._complete(ctx, messages)})


class AgentNode(AINode):
    type = "ai_agent"
    label = "AI agent"
    description = "Let the model call HTTP tools you define until it reaches the goal."
    icon = "bot"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "title": "Goal", "x-ui": "textarea", "minLength": 1},
            "tools": {
                "type": "array",
                "title": "Tools",
                "description": (
                    'List of {"name", "description", "method", "url", "credential_id"?}. '
                    "The model chooses when to call them."
                ),
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "pattern": "^[a-zA-Z0-9_-]{1,64}$"},
                        "description": {"type": "string"},
                        "method": {"enum": ["GET", "POST"]},
                        "url": {"type": "string"},
                        "credential_id": {"type": "string"},
                    },
                    "required": ["name", "description", "method", "url"],
                },
                "x-ui": "json",
            },
            "max_steps": {
                "type": "integer",
                "title": "Max tool calls",
                "minimum": 1,
                "maximum": 8,
                "default": 4,
            },
        },
        "required": ["goal", "tools"],
    }

    async def execute(self, ctx: NodeContext) -> NodeResult:
        tools: list[dict[str, Any]] = ctx.config["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": render_prompt("agent_v1", goal=ctx.config["goal"])},
            {"role": "user", "content": ctx.config["goal"]},
        ]
        trace: list[dict[str, Any]] = []
        for _ in range(int(ctx.config.get("max_steps", 4)) + 1):
            try:
                completion = await ctx.llm.complete_with_tools(messages, tool_definitions(tools))
            except ServiceUnavailableError as exc:
                raise NodeExecutionError(exc.detail) from exc
            ctx.record_usage(self.type, completion.usage)
            if not completion.tool_calls:
                return NodeResult(output={"answer": completion.text or "", "tool_calls": trace})
            if len(trace) >= int(ctx.config.get("max_steps", 4)):
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in completion.tool_calls
                    ],
                }
            )
            for call in completion.tool_calls:
                tool = by_name.get(call.name)
                if tool is None:
                    result: Any = {"error": f"Unknown tool '{call.name}'"}
                else:
                    result = await call_http_tool(ctx, tool, call.arguments)
                trace.append({"tool": call.name, "arguments": call.arguments, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, default=str)[:4000],
                    }
                )
        raise NodeExecutionError("The agent did not finish within the allowed number of steps")
