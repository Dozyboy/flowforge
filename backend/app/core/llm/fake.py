"""Deterministic offline LLM used by tests and by `LLM_PROVIDER=fake` for local demos.

Prompts in `app/core/llm/prompts` start with a `Task: <name>` line; the fake recognises the task
and produces a plausible, rule-based answer:

- summarize: the first sentence of the text
- classify:  the first label that appears as a word in the text (else the last label)
- extract:   values written as `field: value` in the text (else null)
- generate:  an echo of the prompt
- agent:     calls the first tool once, then answers with the tool result
"""

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.core.llm.base import (
    ChatMessage,
    Completion,
    Embeddings,
    StreamDelta,
    StreamEnd,
    StreamEvent,
    ToolCall,
    ToolCompletion,
    Usage,
)

FAKE_MODEL = "fake/model"
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_TASK_RE = re.compile(r"^Task:\s*(\w+)", re.MULTILINE)
_SECTION_RE = r"^{name}:\s*\n(?P<body>.*?)(?=^\w[\w ]*:\s*$|\Z)"


def _section(prompt: str, name: str) -> str:
    match = re.search(_SECTION_RE.format(name=name), prompt, re.MULTILINE | re.DOTALL)
    return match.group("body").strip() if match else ""


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0] if text.strip() else ""


def default_responder(messages: list[ChatMessage]) -> str:
    prompt = "\n".join(m["content"] for m in messages)
    task_match = _TASK_RE.search(prompt)
    task = task_match.group(1) if task_match else "generate"
    text = _section(prompt, "Text")

    if task == "summarize":
        return _first_sentence(text) or "Nothing to summarize."
    if task == "classify":
        labels = [
            line.removeprefix("- ").strip() for line in _section(prompt, "Labels").splitlines()
        ]
        labels = [label for label in labels if label]
        words = {w.lower() for w in _WORD_RE.findall(text)}
        chosen = next(
            (label for label in labels if label.lower() in words), labels[-1] if labels else ""
        )
        return json.dumps({"label": chosen, "reason": "keyword match"})
    if task == "extract":
        fields = json.loads(_section(prompt, "Fields") or "{}")
        result: dict[str, Any] = {}
        for name in fields:
            found = re.search(rf"{re.escape(name)}\s*[:=]\s*([^\n,;]+)", text, re.IGNORECASE)
            result[name] = found.group(1).strip() if found else None
        return json.dumps(result)
    return f"Generated: {_section(prompt, 'Prompt') or prompt[-200:]}"


def hashed_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for word in _WORD_RE.findall(text.lower()):
        bucket = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16) % dimensions
        vector[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeLLMClient:
    def __init__(
        self,
        dimensions: int = 8,
        responder: Callable[[list[ChatMessage]], str] = default_responder,
    ) -> None:
        self.dimensions = dimensions
        self.responder = responder
        self.calls: list[list[ChatMessage]] = []
        self.tool_calls: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
        json_mode: bool = False,
    ) -> Completion:
        self.calls.append(messages)
        text = self.responder(messages)
        return Completion(text=text, usage=self._usage(messages, text))

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> AsyncIterator[StreamEvent]:
        text = self.responder(messages)
        for piece in re.findall(r"\S+\s*", text):
            yield StreamDelta(piece)
        yield StreamEnd(self._usage(messages, text))

    async def embed(self, texts: list[str]) -> Embeddings:
        return Embeddings(
            vectors=[hashed_embedding(t, self.dimensions) for t in texts],
            usage=Usage(model=FAKE_MODEL, prompt_tokens=sum(len(t.split()) for t in texts)),
        )

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> ToolCompletion:
        self.tool_calls.append(messages)
        usage = Usage(model=FAKE_MODEL, prompt_tokens=10, completion_tokens=5)
        tool_results = [m for m in messages if m.get("role") == "tool"]
        if tool_results:
            summary = "; ".join(str(m.get("content", ""))[:200] for m in tool_results)
            return ToolCompletion(text=f"Based on the tools: {summary}", usage=usage)
        if tools:
            name = tools[0]["function"]["name"]
            return ToolCompletion(
                text=None, tool_calls=[ToolCall(id="call_1", name=name, arguments={})], usage=usage
            )
        return ToolCompletion(text="No tools were needed.", usage=usage)

    @staticmethod
    def _usage(messages: list[ChatMessage], text: str) -> Usage:
        prompt_tokens = sum(len(m["content"].split()) for m in messages)
        return Usage(
            model=FAKE_MODEL, prompt_tokens=prompt_tokens, completion_tokens=len(text.split())
        )
