from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.executor import RunExecutor
from app.models import Approval, Run, RunStatus, TriggerType, Workflow
from app.services import scheduler
from app.services.jobs import InMemoryJobQueue
from tests.conftest import Account, AccountFactory
from tests.graphs import edge, graph, load_run, node


async def _publish(
    client: AsyncClient, owner: Account, workflow_graph: dict[str, Any]
) -> tuple[str, str | None]:
    created = await client.post(
        f"{owner.ws}/workflows", json={"name": "Hooked"}, headers=owner.headers
    )
    workflow_id = created.json()["id"]
    await client.patch(
        f"{owner.ws}/workflows/{workflow_id}", json={"graph": workflow_graph}, headers=owner.headers
    )
    published = await client.post(
        f"{owner.ws}/workflows/{workflow_id}/publish", json={}, headers=owner.headers
    )
    return workflow_id, published.json()["webhook_secret"]


WEBHOOK_GRAPH = graph(
    [node("hook", "trigger_webhook"), node("say", "log", {"message": "{{ trigger.body.name }}"})],
    [edge("hook", "say")],
)


async def test_webhook_requires_secret_and_dedupes(
    client: AsyncClient, accounts: AccountFactory, queue: InMemoryJobQueue
) -> None:
    owner = await accounts.owner()
    workflow_id, secret = await _publish(client, owner, WEBHOOK_GRAPH)
    url = f"/api/v1/hooks/{workflow_id}"

    assert (await client.post(url, json={"name": "x"})).status_code == 401
    wrong = await client.post(url, json={}, headers={"X-FlowForge-Secret": "nope"})
    assert wrong.status_code == 401

    headers = {
        "X-FlowForge-Secret": str(secret),
        "Idempotency-Key": "evt_1",
        "Authorization": "Bearer t",
    }
    first = await client.post(url, json={"name": "Ana"}, headers=headers)
    again = await client.post(url, json={"name": "Ana"}, headers=headers)
    assert first.status_code == 202
    assert again.status_code == 200
    assert again.json() == {**first.json(), "duplicate": True}
    assert len(queue.named("execute_run")) == 1

    via_query = await client.post(f"{url}?secret={secret}&source=crm", data={"name": "Bo"})
    assert via_query.status_code == 202

    detail = await client.get(
        f"{owner.ws}/runs/{via_query.json()['run_id']}", headers=owner.headers
    )
    payload = detail.json()["trigger_payload"]
    assert payload["body"] == {"name": "Bo"}
    assert payload["query"] == {"source": "crm"}
    first_payload = (
        await client.get(f"{owner.ws}/runs/{first.json()['run_id']}", headers=owner.headers)
    ).json()["trigger_payload"]
    assert "authorization" not in first_payload["headers"]
    assert "x-flowforge-secret" not in first_payload["headers"]


async def test_inactive_or_unknown_webhooks_are_not_found(
    client: AsyncClient, accounts: AccountFactory
) -> None:
    owner = await accounts.owner()
    workflow_id, secret = await _publish(client, owner, WEBHOOK_GRAPH)
    await client.post(
        f"{owner.ws}/workflows/{workflow_id}/activation",
        json={"active": False},
        headers=owner.headers,
    )
    response = await client.post(
        f"/api/v1/hooks/{workflow_id}", json={}, headers={"X-FlowForge-Secret": str(secret)}
    )
    assert response.status_code == 404


async def test_rotating_the_secret_invalidates_the_old_one(
    client: AsyncClient, accounts: AccountFactory
) -> None:
    owner = await accounts.owner()
    workflow_id, old_secret = await _publish(client, owner, WEBHOOK_GRAPH)
    rotated = await client.post(
        f"{owner.ws}/workflows/{workflow_id}/webhook-secret", headers=owner.headers
    )
    new_secret = rotated.json()["webhook_secret"]
    assert rotated.json()["webhook_url"].endswith(f"/api/v1/hooks/{workflow_id}")
    url = f"/api/v1/hooks/{workflow_id}"
    assert (
        await client.post(url, json={}, headers={"X-FlowForge-Secret": str(old_secret)})
    ).status_code == 401
    assert (
        await client.post(url, json={}, headers={"X-FlowForge-Secret": new_secret})
    ).status_code == 202


async def test_approval_link_flow(
    client: AsyncClient,
    accounts: AccountFactory,
    session: AsyncSession,
    executor: RunExecutor,
    queue: InMemoryJobQueue,
) -> None:
    owner = await accounts.owner()
    approval_graph = graph(
        [
            node("hook", "trigger_webhook"),
            node(
                "gate",
                "approval",
                {
                    "approvers": ["boss@example.com"],
                    "message": "Pay {{ trigger.body.amount }} USD?",
                },
            ),
            node("paid", "log", {"message": "paid"}),
        ],
        [edge("hook", "gate"), edge("gate", "paid", "approved")],
    )
    workflow_id, secret = await _publish(client, owner, approval_graph)
    started = await client.post(
        f"/api/v1/hooks/{workflow_id}",
        json={"amount": 120},
        headers={"X-FlowForge-Secret": str(secret)},
    )
    run_id = started.json()["run_id"]
    from uuid import UUID

    await executor.execute(UUID(run_id))
    token = queue.named("send_email")[0]["text"].rsplit("/approvals/", 1)[1].strip()

    pending = await client.get(f"{owner.ws}/approvals", headers=owner.headers)
    assert pending.json()[0]["message"] == "Pay 120 USD?"

    view = await client.get(f"/api/v1/approvals/{token}")
    assert view.json()["status"] == "pending"
    assert view.json()["workflow_name"] == "Hooked"

    decided = await client.post(
        f"/api/v1/approvals/{token}", json={"decision": "approve", "name": "Boss", "comment": "ok"}
    )
    assert decided.json()["status"] == "approved"
    assert queue.named("execute_run")[-1] == {"run_id": run_id}
    twice = await client.post(f"/api/v1/approvals/{token}", json={"decision": "reject"})
    assert twice.status_code == 400

    await executor.execute(UUID(run_id))
    run, steps = await load_run(session, UUID(run_id))
    assert run.status == RunStatus.SUCCEEDED
    assert steps["gate"].output["decided_by"] == "Boss"
    assert steps["paid"].status == "succeeded"

    assert (await client.get("/api/v1/approvals/not-a-real-token")).status_code == 404


async def test_expired_approvals_resume_on_rejected_branch(
    accounts: AccountFactory, session: AsyncSession, executor: RunExecutor, queue: InMemoryJobQueue
) -> None:
    from app.services import approvals as approval_service
    from tests.graphs import make_run, make_workflow

    owner = await accounts.owner()
    workflow = await make_workflow(
        session,
        owner.workspace,
        graph(
            [
                node("t", "trigger_manual"),
                node("gate", "approval", {"approvers": ["a@example.com"], "message": "?"}),
                node("no", "log", {"message": "expired"}),
            ],
            [edge("t", "gate"), edge("gate", "no", "rejected")],
        ),
    )
    run = await make_run(session, workflow)
    await executor.execute(run.id)
    approval = await session.scalar(select(Approval))
    assert approval is not None
    approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    assert await approval_service.expire_overdue(session, queue) == 1
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)
    assert run.status == RunStatus.SUCCEEDED
    assert steps["gate"].output["status"] == "expired"
    assert steps["no"].status == "succeeded"


async def test_scheduler_tick_starts_due_workflows_once(
    client: AsyncClient, accounts: AccountFactory, session: AsyncSession, queue: InMemoryJobQueue
) -> None:
    owner = await accounts.owner()
    scheduled = graph(
        [
            node("tick", "trigger_schedule", {"cron": "*/5 * * * *", "timezone": "UTC"}),
            node("say", "log", {"message": "hi"}),
        ],
        [edge("tick", "say")],
    )
    workflow_id, _ = await _publish(client, owner, scheduled)
    workflow = await session.get(Workflow, workflow_id, populate_existing=True)
    assert workflow is not None and workflow.next_run_at is not None
    due_at = workflow.next_run_at

    assert await scheduler.tick(session, queue, now=due_at - timedelta(seconds=1)) == 0
    assert await scheduler.tick(session, queue, now=due_at) == 1
    assert await scheduler.tick(session, queue, now=due_at) == 0

    await session.refresh(workflow)
    assert workflow.next_run_at == due_at + timedelta(minutes=5)
    run = await session.scalar(select(Run).where(Run.workflow_id == workflow.id))
    assert run is not None
    assert run.trigger_type == TriggerType.SCHEDULE
    assert run.trigger_payload == {"scheduled_at": due_at.isoformat()}


async def test_stuck_runs_are_failed(accounts: AccountFactory, session: AsyncSession) -> None:
    from tests.graphs import make_run, make_workflow

    owner = await accounts.owner()
    workflow = await make_workflow(
        session, owner.workspace, graph([node("t", "trigger_manual")], [])
    )
    run = await make_run(session, workflow)
    run.status = RunStatus.RUNNING
    run.updated_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()
    assert await scheduler.fail_stuck_runs(session, timedelta(minutes=30)) == 1
    await session.refresh(run)
    assert run.status == RunStatus.FAILED
