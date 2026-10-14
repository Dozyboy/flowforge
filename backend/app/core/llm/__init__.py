from functools import lru_cache

from app.config import get_settings
from app.core.llm.base import (
    ChatMessage,
    Completion,
    Embeddings,
    LLMClient,
    StreamDelta,
    StreamEnd,
    StreamEvent,
    Usage,
)
from app.core.llm.fake import FakeLLMClient
from app.core.llm.openrouter import OpenRouterClient
from app.core.llm.prompts import render_prompt


@lru_cache
def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "fake":
        return FakeLLMClient(settings.embedding_dimensions)
    return OpenRouterClient(settings)


__all__ = [
    "ChatMessage",
    "Completion",
    "Embeddings",
    "FakeLLMClient",
    "LLMClient",
    "OpenRouterClient",
    "StreamDelta",
    "StreamEnd",
    "StreamEvent",
    "Usage",
    "get_llm_client",
    "render_prompt",
]
