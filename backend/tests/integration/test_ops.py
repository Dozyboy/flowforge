from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.core import rate_limit
from app.core.errors import RateLimitedError


async def test_health_and_ready(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
    generated = await client.get("/health")
    assert len(generated.headers["x-request-id"]) == 32


async def test_metrics_endpoint_uses_route_templates(client: AsyncClient) -> None:
    await client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000")
    body = (await client.get("/metrics")).text
    assert 'route="/api/v1/workspaces/{workspace_id}"' in body
    assert "00000000-0000" not in body


async def test_unknown_route_returns_problem_details(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["instance"] == "/api/v1/nope"


async def test_rate_limiter_blocks_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    for _ in range(3):
        await rate_limit.hit("test:key", limit=3, window_seconds=60)
    with pytest.raises(RateLimitedError) as error:
        await rate_limit.hit("test:key", limit=3, window_seconds=60)
    assert 0 < error.value.extra["retry_after"] <= 60


async def test_login_is_rate_limited(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    # Freeze the limiter's clock so all requests land in the same fixed window.
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(time=lambda: 1_800_000_000.0))
    payload = {"email": "a@example.com", "password": "whatever-123"}
    statuses = [
        (await client.post("/api/v1/auth/login", json=payload)).status_code for _ in range(21)
    ]
    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429

    # Session refresh has a separate budget, so signed-in users are not locked out.
    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 401
