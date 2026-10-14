import hmac
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, NotFoundError
from app.core.security import hash_token
from app.models import Run, TriggerType, WebhookEvent, Workflow, Workspace
from app.services import runs
from app.services.jobs import JobQueue

SENSITIVE_HEADERS = {"authorization", "cookie", "x-flowforge-secret"}


async def trigger(
    session: AsyncSession,
    queue: JobQueue,
    workflow_id: uuid.UUID,
    *,
    secret: str | None,
    body: Any,
    query: dict[str, str],
    headers: dict[str, str],
    idempotency_key: str | None,
) -> tuple[Run, bool]:
    """Start a run from a webhook call. Returns (run, created); created is False for duplicates."""
    workflow = await session.get(Workflow, workflow_id)
    if (
        workflow is None
        or not workflow.is_active
        or workflow.published_version_id is None
        or workflow.webhook_secret_hash is None
    ):
        raise NotFoundError("Webhook not found or the workflow is not active")
    if not secret or not hmac.compare_digest(hash_token(secret), workflow.webhook_secret_hash):
        raise AuthenticationError("Invalid webhook secret")

    if idempotency_key:
        existing = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.workflow_id == workflow.id,
                WebhookEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            run = await session.get(Run, existing.run_id)
            if run is not None:
                return run, False

    workspace = await session.get(Workspace, workflow.workspace_id)
    if workspace is None:
        raise NotFoundError("Webhook not found")
    payload = {
        "body": body,
        "query": query,
        "headers": {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS},
    }
    run = await runs.start_run(
        session, queue, workspace, workflow, trigger_type=TriggerType.WEBHOOK, payload=payload
    )
    if idempotency_key:
        session.add(
            WebhookEvent(workflow_id=workflow.id, idempotency_key=idempotency_key, run_id=run.id)
        )
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent delivery with the same key won the race; keep its run.
            await session.rollback()
            existing = await session.scalar(
                select(WebhookEvent).where(
                    WebhookEvent.workflow_id == workflow.id,
                    WebhookEvent.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                await runs.cancel_run(session, run)
                winner = await session.get(Run, existing.run_id)
                if winner is not None:
                    return winner, False
    return run, True
