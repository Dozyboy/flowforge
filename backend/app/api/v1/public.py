"""Public endpoints: incoming webhooks and approval links. No user session required."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import QueueDep, SessionDep
from app.core.errors import AppError
from app.core.rate_limit import client_ip, hit
from app.schemas.run import ApprovalDecision, ApprovalPublicOut, WebhookAccepted
from app.services import approvals, webhooks

router = APIRouter(tags=["public"])

MAX_WEBHOOK_BODY_BYTES = 1024 * 1024
WEBHOOKS_PER_MINUTE = 120


async def _parse_body(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BODY_BYTES:
        raise AppError("Request body is larger than 1 MB")
    if not raw:
        return {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AppError("Body is not valid JSON") from exc
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        return {k: v for k, v in form.items() if isinstance(v, str)}
    return raw.decode("utf-8", errors="replace")


@router.post("/hooks/{workflow_id}", response_model=WebhookAccepted)
async def receive_webhook(
    workflow_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    queue: QueueDep,
    x_flowforge_secret: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Start a run. Send the secret in `X-FlowForge-Secret` (or `?secret=`); optional
    `Idempotency-Key` makes retries from the sender start only one run."""
    await hit(f"webhook:{workflow_id}:{client_ip(request)}", WEBHOOKS_PER_MINUTE, 60)
    query = dict(request.query_params)
    secret = x_flowforge_secret or query.pop("secret", None)
    run, created = await webhooks.trigger(
        session,
        queue,
        workflow_id,
        secret=secret,
        body=await _parse_body(request),
        query=query,
        headers=dict(request.headers),
        idempotency_key=(idempotency_key or "")[:200] or None,
    )
    body = WebhookAccepted(run_id=run.id, status=run.status, duplicate=not created)
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
    )


@router.get("/approvals/{token}", response_model=ApprovalPublicOut)
async def view_approval(token: str, session: SessionDep) -> ApprovalPublicOut:
    view = await approvals.view(session, token)
    approval = view.approval
    return ApprovalPublicOut(
        workflow_name=view.workflow_name,
        message=approval.message,
        status=approval.status,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        decided_by=approval.decided_by,
        run_status=view.run_status,
    )


@router.post("/approvals/{token}", response_model=ApprovalPublicOut)
async def decide_approval(
    token: str, body: ApprovalDecision, request: Request, session: SessionDep, queue: QueueDep
) -> ApprovalPublicOut:
    await hit(f"approval:{client_ip(request)}", 30, 60)
    await approvals.decide(
        session,
        queue,
        token,
        approve=body.decision == "approve",
        decided_by=body.name,
        comment=body.comment,
    )
    return await view_approval(token, session)
