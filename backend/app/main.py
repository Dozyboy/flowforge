from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import api_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, metrics_endpoint
from app.core.realtime import hub
from app.core.redis import close_redis, get_redis
from app.db.session import dispose_engine, get_engine
from app.services.jobs import job_queue


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await hub.start()
    yield
    await hub.stop()
    await job_queue.close()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "development")

    # No CORS middleware: the dashboard and approval pages reach the API through the
    # same-origin Next.js proxy, and webhooks are server-to-server calls.
    app = FastAPI(
        title="FlowForge API",
        version="1.0.0",
        description="AI workflow automation: visual workflows, execution engine, runs, approvals.",
        lifespan=lifespan,
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
        healthy = all(value == "ok" for value in checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status_code=200 if healthy else 503,
        )

    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)
    return app


app = create_app()
