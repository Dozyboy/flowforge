import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, cast

from openai import APIError, AsyncOpenAI, DefaultAsyncHttpxClient
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from app.config import Settings
from app.core.errors import ServiceUnavailableError
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
from app.core.metrics import LLM_REQUESTS_TOTAL

EMBEDDING_BATCH_SIZE = 96


def _to_params(messages: list[ChatMessage]) -> list[ChatCompletionMessageParam]:
    return [cast(ChatCompletionMessageParam, dict(m)) for m in messages]


def _usage_from(model: str, usage: Any) -> Usage:
    if usage is None:
        return Usage(model=model)
    extra = getattr(usage, "model_extra", None) or {}
    cost = getattr(usage, "cost", None) or extra.get("cost") or 0
    return Usage(
        model=model,
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        cost_usd=Decimal(str(cost)),
    )


class OpenRouterClient:
    """LLM client for OpenRouter's OpenAI-compatible API.

    Fallback models are passed to OpenRouter in the `models` field, so routing to the next model
    on provider errors happens server-side in a single request.
    """

    def __init__(
        self, settings: Settings, http_client: DefaultAsyncHttpxClient | None = None
    ) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value() or "missing",
            base_url=settings.openrouter_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
            default_headers={"X-Title": settings.app_name, "HTTP-Referer": settings.public_app_url},
            http_client=http_client,
        )

    def _ensure_configured(self) -> None:
        if not self._settings.llm_enabled:
            raise ServiceUnavailableError("The AI provider is not configured")

    def _routing_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"usage": {"include": True}}
        if self._settings.openrouter_fallback_models:
            body["models"] = [
                self._settings.openrouter_chat_model,
                *self._settings.openrouter_fallback_models,
            ]
        return body

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
        json_mode: bool = False,
    ) -> Completion:
        self._ensure_configured()
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.openrouter_chat_model,
                messages=_to_params(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=self._routing_body(),
                **kwargs,
            )
        except APIError as exc:
            LLM_REQUESTS_TOTAL.labels("chat", self._settings.openrouter_chat_model, "error").inc()
            raise ServiceUnavailableError("The AI provider failed to respond") from exc
        model = response.model or self._settings.openrouter_chat_model
        LLM_REQUESTS_TOTAL.labels("chat", model, "ok").inc()
        text = (response.choices[0].message.content or "") if response.choices else ""
        return Completion(text=text, usage=_usage_from(model, response.usage))

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> AsyncIterator[StreamEvent]:
        self._ensure_configured()
        model = self._settings.openrouter_chat_model
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=_to_params(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=self._routing_body(),
            )
            usage: Any = None
            async for chunk in response:
                model = chunk.model or model
                if chunk.usage is not None:
                    usage = chunk.usage
                for choice in chunk.choices:
                    if choice.delta and choice.delta.content:
                        yield StreamDelta(choice.delta.content)
        except APIError as exc:
            LLM_REQUESTS_TOTAL.labels("chat_stream", model, "error").inc()
            raise ServiceUnavailableError("The AI provider failed to respond") from exc
        LLM_REQUESTS_TOTAL.labels("chat_stream", model, "ok").inc()
        yield StreamEnd(_usage_from(model, usage))

    async def embed(self, texts: list[str]) -> Embeddings:
        self._ensure_configured()
        model = self._settings.openrouter_embedding_model
        vectors: list[list[float]] = []
        prompt_tokens = 0
        cost = Decimal(0)
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            try:
                response = await self._client.embeddings.create(
                    model=model,
                    input=batch,
                    dimensions=self._settings.embedding_dimensions,
                    encoding_format="float",
                )
            except APIError as exc:
                LLM_REQUESTS_TOTAL.labels("embedding", model, "error").inc()
                raise ServiceUnavailableError("The embedding provider failed to respond") from exc
            LLM_REQUESTS_TOTAL.labels("embedding", model, "ok").inc()
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
            batch_usage = _usage_from(model, response.usage)
            prompt_tokens += batch_usage.prompt_tokens
            cost += batch_usage.cost_usd
        return Embeddings(
            vectors=vectors,
            usage=Usage(model=model, prompt_tokens=prompt_tokens, cost_usd=cost),
        )

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> ToolCompletion:
        self._ensure_configured()
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.openrouter_chat_model,
                messages=cast(list[ChatCompletionMessageParam], messages),
                tools=cast(list[ChatCompletionToolParam], tools),
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=self._routing_body(),
            )
        except APIError as exc:
            LLM_REQUESTS_TOTAL.labels("tools", self._settings.openrouter_chat_model, "error").inc()
            raise ServiceUnavailableError("The AI provider failed to respond") from exc
        model = response.model or self._settings.openrouter_chat_model
        LLM_REQUESTS_TOTAL.labels("tools", model, "ok").inc()
        usage = _usage_from(model, response.usage)
        if not response.choices:
            return ToolCompletion(text="", usage=usage)
        message = response.choices[0].message
        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            function = getattr(call, "function", None)
            if function is None:
                continue
            try:
                arguments = json.loads(function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(
                ToolCall(
                    id=call.id,
                    name=function.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        if calls:
            return ToolCompletion(text=None, tool_calls=calls, usage=usage)
        return ToolCompletion(text=message.content or "", usage=usage)
