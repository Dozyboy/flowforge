"""OpenRouterClient against mocked HTTP responses in the OpenAI-compatible wire format.

The openai SDK ships its own HTTP stack (httpx2), so responses are mocked with a
`httpx2.MockTransport` passed in as the client's `http_client`. These tests pin down the request
we send (model, fallbacks, usage accounting) and how responses, streams, usage and errors are
parsed, without needing a real API key.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from openai import DefaultAsyncHttpxClient

from app.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.llm import OpenRouterClient, StreamDelta, StreamEnd

BASE = "https://openrouter.test/api/v1"


class Recorder:
    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.respond = respond
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.respond(request)

    @property
    def last_body(self) -> dict[str, Any]:
        return dict(json.loads(self.requests[-1].content))


def _client(recorder: Recorder, **overrides: object) -> OpenRouterClient:
    values: dict[str, object] = {
        "llm_provider": "openrouter",
        "openrouter_api_key": "sk-or-test",
        "openrouter_base_url": BASE,
        "openrouter_chat_model": "openai/gpt-4o-mini",
        "openrouter_fallback_models": ["meta-llama/llama-3.3-70b-instruct"],
        "embedding_dimensions": 3,
    }
    values.update(overrides)
    settings = Settings.model_validate(values)
    http_client = DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder))
    return OpenRouterClient(settings, http_client=http_client)


def _completion(text: str) -> dict[str, object]:
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 1,
        "model": "openai/gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
            "cost": 0.000123,
        },
    }


async def test_complete_sends_routing_options_and_parses_usage() -> None:
    recorder = Recorder(lambda _: httpx2.Response(200, json=_completion("Hello")))
    client = _client(recorder)

    result = await client.complete([{"role": "user", "content": "Hi"}], json_mode=True)

    assert result.text == "Hello"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 5
    assert result.usage.cost_usd == Decimal("0.000123")
    request = recorder.requests[-1]
    assert str(request.url) == f"{BASE}/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    body = recorder.last_body
    assert body["model"] == "openai/gpt-4o-mini"
    assert body["models"] == ["openai/gpt-4o-mini", "meta-llama/llama-3.3-70b-instruct"]
    assert body["usage"] == {"include": True}
    assert body["response_format"] == {"type": "json_object"}


async def test_stream_yields_deltas_then_usage() -> None:
    chunks: list[dict[str, Any]] = [
        {"choices": [{"index": 0, "delta": {"content": "Refunds "}}]},
        {"choices": [{"index": 0, "delta": {"content": "take 5 days."}}]},
        {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 4, "cost": 0.0002}},
    ]
    stream = "".join(
        "data: "
        + json.dumps(
            {"id": "g", "object": "chat.completion.chunk", "created": 1, "model": "m", **c}
        )
        + "\n\n"
        for c in chunks
    )
    stream += "data: [DONE]\n\n"
    recorder = Recorder(
        lambda _: httpx2.Response(
            200, content=stream.encode(), headers={"content-type": "text/event-stream"}
        )
    )
    client = _client(recorder)

    events = [e async for e in client.stream([{"role": "user", "content": "refunds?"}])]

    assert [e.text for e in events if isinstance(e, StreamDelta)] == ["Refunds ", "take 5 days."]
    end = events[-1]
    assert isinstance(end, StreamEnd)
    assert end.usage.prompt_tokens == 30
    assert end.usage.cost_usd == Decimal("0.0002")
    assert recorder.last_body["stream_options"] == {"include_usage": True}


async def test_embed_keeps_input_order_and_requests_dimensions() -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "openai/text-embedding-3-small",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )
    )
    client = _client(recorder)

    result = await client.embed(["first", "second"])

    assert result.vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert result.usage.prompt_tokens == 8
    assert recorder.last_body["dimensions"] == 3
    assert recorder.last_body["input"] == ["first", "second"]


async def test_provider_errors_become_service_unavailable() -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(400, json={"error": {"message": "bad model", "code": 400}})
    )
    client = _client(recorder)
    with pytest.raises(ServiceUnavailableError):
        await client.complete([{"role": "user", "content": "Hi"}])


async def test_missing_api_key_is_reported() -> None:
    recorder = Recorder(lambda _: httpx2.Response(500))
    client = _client(recorder, openrouter_api_key="")
    with pytest.raises(ServiceUnavailableError, match="not configured"):
        await client.embed(["x"])
    assert recorder.requests == []
