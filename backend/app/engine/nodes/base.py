"""Base class for node types (see docs/adr/0003-node-plugin-registry.md)."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from jsonschema import Draft202012Validator

from app.core.llm import LLMClient, Usage
from app.engine.graph import Node

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Run, StepRun
    from app.services.jobs import JobQueue


class NodeCategory(StrEnum):
    TRIGGER = "trigger"
    AI = "ai"
    LOGIC = "logic"
    DATA = "data"
    INTEGRATION = "integration"


class NodeExecutionError(Exception):
    """A step failed. `retryable=False` skips retries (configuration mistakes, 4xx responses)."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Wait:
    """The step pauses the run until `resume()` returns a result."""

    resume_at: datetime | None = None
    output: Any = None


@dataclass(frozen=True)
class NodeResult:
    output: Any = None
    branch: str | None = None
    wait: Wait | None = None


ChildRunner = Callable[[uuid.UUID, dict[str, Any]], Awaitable[dict[str, Any]]]
CredentialResolver = Callable[[str, tuple[str, ...]], Awaitable[dict[str, Any]]]


@dataclass
class NodeContext:
    """Everything a node may use while executing. Built by the executor for each step."""

    node: Node
    config: dict[str, Any]
    run: "Run"
    workflow_name: str
    session: "AsyncSession"
    llm: LLMClient
    http: "httpx.AsyncClient"
    queue: "JobQueue"
    resolve_credential: CredentialResolver
    run_child: ChildRunner
    parent_outputs: dict[str, Any] = field(default_factory=dict)
    usage: list[tuple[str, Usage]] = field(default_factory=list)

    def record_usage(self, kind: str, usage: Usage) -> None:
        self.usage.append((kind, usage))


class NodeType:
    type: ClassVar[str]
    label: ClassVar[str]
    category: ClassVar[NodeCategory]
    description: ClassVar[str]
    icon: ClassVar[str] = "box"
    config_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    static_handles: ClassVar[list[str]] = []
    dynamic_handles_key: ClassVar[str | None] = None
    dynamic_handles_extra: ClassVar[list[str]] = []
    pausable: ClassVar[bool] = False

    def output_handles(self, config: dict[str, Any]) -> list[str]:
        handles = list(self.static_handles)
        if self.dynamic_handles_key:
            values = config.get(self.dynamic_handles_key)
            if isinstance(values, list):
                handles.extend(str(v) for v in values if isinstance(v, str) and v)
            handles.extend(self.dynamic_handles_extra)
        return handles

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        validator = Draft202012Validator(self.config_schema)
        problems = []
        for error in sorted(validator.iter_errors(config), key=lambda e: list(e.path)):
            where = ".".join(str(p) for p in error.path)
            problems.append(f"{where}: {error.message}" if where else error.message)
        return problems + self.extra_validation(config)

    def extra_validation(self, config: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, ctx: NodeContext) -> NodeResult:
        raise NotImplementedError

    async def resume(self, ctx: NodeContext, step: "StepRun") -> NodeResult | None:
        """For pausable nodes: return the final result, or None while still waiting."""
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "config_schema": self.config_schema,
            "static_handles": self.static_handles,
            "dynamic_handles_key": self.dynamic_handles_key,
            "dynamic_handles_extra": self.dynamic_handles_extra,
        }


def require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise NodeExecutionError(
            f"'{name}' must be a list, got {type(value).__name__}", retryable=False
        )
    return value
