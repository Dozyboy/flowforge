"""Outbound HTTP for workflow nodes with SSRF protection.

User-configured URLs must not reach the internal network (cloud metadata endpoints, databases,
admin panels). Every hop — including redirects — must resolve only to public IP addresses unless
ALLOW_PRIVATE_NETWORK_REQUESTS is enabled for development.
"""

import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings
from app.engine.nodes.base import NodeExecutionError

MAX_REDIRECTS = 5


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: Any


async def _ensure_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise NodeExecutionError(f"Only http(s) URLs are allowed: {url}", retryable=False)
    if get_settings().allow_private_network_requests:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise NodeExecutionError(f"Could not resolve host {parsed.hostname}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise NodeExecutionError(
                "Requests to private or internal network addresses are blocked", retryable=False
            )


def _decode(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text
    return response.text


async def safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    content: str | bytes | None = None,
    data: dict[str, Any] | None = None,
) -> HttpResult:
    max_bytes = get_settings().http_node_max_response_bytes
    for _ in range(MAX_REDIRECTS + 1):
        await _ensure_public(url)
        request = client.build_request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body if json_body is not None and content is None and data is None else None,
            content=content,
            data=data,
        )
        try:
            response = await client.send(request, stream=True, follow_redirects=False)
        except httpx.TimeoutException as exc:
            raise NodeExecutionError(f"Request to {url} timed out") from exc
        except httpx.HTTPError as exc:
            raise NodeExecutionError(f"Request to {url} failed: {exc}") from exc
        try:
            if response.is_redirect and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                if response.status_code in (301, 302, 303):
                    method, json_body, content, data = "GET", None, None, None
                continue
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise NodeExecutionError("Response is too large", retryable=False)
        finally:
            await response.aclose()
        full = httpx.Response(response.status_code, headers=response.headers, content=bytes(body))
        return HttpResult(
            status=full.status_code,
            headers={k.lower(): v for k, v in full.headers.items()},
            body=_decode(full),
        )
    raise NodeExecutionError("Too many redirects", retryable=False)


def raise_for_status(result: HttpResult, service: str) -> None:
    if result.status >= 400:
        detail = result.body if isinstance(result.body, str) else json.dumps(result.body)
        raise NodeExecutionError(
            f"{service} responded with HTTP {result.status}: {detail[:300]}",
            retryable=result.status >= 500 or result.status == 429,
        )
