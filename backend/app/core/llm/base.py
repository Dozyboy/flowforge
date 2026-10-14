from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal(0)


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage


@dataclass(frozen=True)
class Embeddings:
    vectors: list[list[float]]
    usage: Usage


@dataclass(frozen=True)
class StreamDelta:
    text: str


@dataclass(frozen=True)
class StreamEnd:
    usage: Usage


StreamEvent = StreamDelta | StreamEnd


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCompletion:
    """Either a final answer (`text`) or a request to call tools (`tool_calls`)."""

    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(model="unknown"))


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
        json_mode: bool = False,
    ) -> Completion: ...

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> AsyncIterator[StreamEvent]: ...

    async def embed(self, texts: list[str]) -> Embeddings: ...

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> ToolCompletion:
        """`messages` use the OpenAI chat format, including `tool` results."""
        ...
