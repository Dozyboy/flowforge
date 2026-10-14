import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUESTS_TOTAL = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["method", "route"]
)
LLM_REQUESTS_TOTAL = Counter("llm_requests_total", "LLM API calls", ["kind", "model", "outcome"])
RUNS_FINISHED_TOTAL = Counter(
    "workflow_runs_finished_total", "Workflow runs that reached a final state", ["status"]
)
STEP_DURATION = Histogram(
    "workflow_step_duration_seconds",
    "Time spent executing one step, retries included",
    ["node_type", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)


def _route_template(scope: Scope) -> str:
    """Label requests by route template (/documents/{document_id}) to keep cardinality low.

    Nested routers only know their own relative path, so the template is rebuilt from the
    request path by putting placeholders back where path parameters matched.
    """
    if scope.get("route") is None:
        return "unmatched"
    placeholders = {str(value): name for name, value in (scope.get("path_params") or {}).items()}
    segments = scope["path"].split("/")
    return "/".join(
        f"{{{placeholders[segment]}}}" if segment in placeholders else segment
        for segment in segments
    )


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = _route_template(scope)
            REQUESTS_TOTAL.labels(scope["method"], route, str(status_code)).inc()
            REQUEST_DURATION.labels(scope["method"], route).observe(time.perf_counter() - started)


async def metrics_endpoint(_: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
