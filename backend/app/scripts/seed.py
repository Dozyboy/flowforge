"""Create a demo account with published workflows and a few real runs.

Usage: `python -m app.scripts.seed` (or `make seed`). Safe to run more than once.
Sign in with demo@flowforge.dev / demo-password.
"""

import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select, update

from app.core.llm import get_llm_client
from app.core.security import hash_password
from app.db.session import dispose_engine, get_session_factory
from app.engine.executor import EngineDeps, RunExecutor
from app.models import Run, StepRun, TriggerType, User
from app.services import email as email_service
from app.services import runs, workflows, workspaces
from app.services.audit import Actor
from app.services.jobs import InMemoryJobQueue

DEMO_EMAIL = "demo@flowforge.dev"
DEMO_PASSWORD = "demo-password"  # noqa: S105 - public demo credentials

SAMPLE_MESSAGES = [
    {"email": "maya@example.com", "message": "Please refund my order, the grinder arrived broken."},
    {"email": "leo@example.com", "message": "There is a bug: the export button crashes the app."},
    {"email": "priya@example.com", "message": "I have a question about pricing for teams."},
]
SAMPLE_LEADS = [
    {"email": "cto@bigco.example", "message": "company: BigCo\nbudget: 25000\ntimeline: Q1"},
    {"email": "hi@tiny.example", "message": "company: Tiny Studio\nbudget: 800\ntimeline: someday"},
]

# Two weeks of history so the dashboard, run list and failure views look like a live account.
HISTORY_MESSAGES = [
    {"email": "omar@example.com", "message": "There is a bug: the invoice PDF is blank."},
    {"email": "lena@example.com", "message": "Bug report: login loops back to the sign-in page."},
    {"email": "tom@example.com", "message": "Quick question: can I add a second admin?"},
    {"email": "ines@example.com", "message": "I have a question about the annual plan discount."},
    {"email": "raj@example.com", "message": "The mobile app has a bug when uploading photos."},
    {"email": "zoe@example.com", "message": "Question: do you have an API for exports?"},
]
HISTORY_LEADS = [
    {"email": "ops@acme.example", "message": "company: Acme\nbudget: 12000\ntimeline: Q1"},
    {"email": "hi@studio.example", "message": "company: Studio\nbudget: 1500\ntimeline: later"},
    {"email": "cfo@globex.example", "message": "company: Globex\nbudget: 40000\ntimeline: now"},
]
# Calls a host that does not exist, so its runs fail and show retries and error details.
CRM_SYNC_GRAPH = {
    "nodes": [
        {
            "id": "start",
            "type": "trigger_manual",
            "position": {"x": 200, "y": 0},
            "data": {"label": "Run sync", "config": {"sample_payload": {"since": "yesterday"}}},
        },
        {
            "id": "push_orders",
            "type": "http_request",
            "position": {"x": 200, "y": 130},
            "data": {
                "label": "Push orders to CRM",
                "config": {"method": "POST", "url": "https://crm.example.invalid/api/orders"},
                "settings": {"retries": 1, "retry_delay_seconds": 1},
            },
        },
        {
            "id": "done",
            "type": "log",
            "position": {"x": 200, "y": 260},
            "data": {"label": "Log result", "config": {"message": "Synced orders"}},
        },
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "push_orders"},
        {"id": "e2", "source": "push_orders", "target": "done"},
    ],
}


async def _backdate(run_ids: list[uuid.UUID]) -> None:
    """Spread freshly executed runs over the last two weeks (runs and their steps together)."""
    rng = random.Random(7)  # noqa: S311 - deterministic demo data, not security
    async with get_session_factory()() as session:
        for run_id in run_ids:
            offset = timedelta(days=rng.randint(1, 13), hours=rng.randint(0, 10))
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    created_at=Run.created_at - offset,
                    started_at=Run.started_at - offset,
                    finished_at=Run.finished_at - offset,
                )
            )
            await session.execute(
                update(StepRun)
                .where(StepRun.run_id == run_id)
                .values(
                    started_at=StepRun.started_at - offset,
                    finished_at=StepRun.finished_at - offset,
                )
            )
        await session.commit()


async def seed() -> None:
    queue = InMemoryJobQueue()
    async with get_session_factory()() as session:
        if await session.scalar(select(User).where(User.email == DEMO_EMAIL)):
            print(f"Demo account already exists: {DEMO_EMAIL} / {DEMO_PASSWORD}")
            return
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            full_name="Demo Owner",
            email_verified_at=datetime.now(UTC),
        )
        session.add(user)
        await session.commit()
        workspace = await workspaces.create_workspace(session, user, "Northwind Ops")
        actor = Actor(user_id=user.id)

        created = {}
        for template_id in ("support-triage", "lead-qualification", "daily-digest"):
            workflow = await workflows.create_from_template(session, workspace, actor, template_id)
            await workflows.publish(session, workflow, actor, "Initial version")
            created[template_id] = workflow

        run_ids = []
        for payload in SAMPLE_MESSAGES:
            run = await runs.start_run(
                session,
                queue,
                workspace,
                created["support-triage"],
                trigger_type=TriggerType.WEBHOOK,
                payload={"body": payload, "query": {}, "headers": {}},
            )
            run_ids.append(run.id)
        for payload in SAMPLE_LEADS:
            run = await runs.start_run(
                session,
                queue,
                workspace,
                created["lead-qualification"],
                trigger_type=TriggerType.WEBHOOK,
                payload={"body": payload, "query": {}, "headers": {}},
            )
            run_ids.append(run.id)

        crm = await workflows.create_workflow(
            session,
            workspace,
            actor,
            name="Sync orders to CRM",
            description="Push yesterday's orders to the CRM every night.",
            graph=CRM_SYNC_GRAPH,
        )
        await workflows.publish(session, crm, actor, "Initial version")
        history_ids = []
        run_payload: dict[str, Any]
        for index in range(18):
            if index % 6 == 5:
                workflow, run_payload, trigger = crm, {"since": "yesterday"}, TriggerType.MANUAL
            elif index % 3 == 0:
                workflow, trigger = created["lead-qualification"], TriggerType.WEBHOOK
                lead = HISTORY_LEADS[index % len(HISTORY_LEADS)]
                run_payload = {"body": lead, "query": {}, "headers": {}}
            else:
                workflow, trigger = created["support-triage"], TriggerType.WEBHOOK
                body = HISTORY_MESSAGES[index % len(HISTORY_MESSAGES)]
                run_payload = {"body": body, "query": {}, "headers": {}}
            run = await runs.start_run(
                session, queue, workspace, workflow, trigger_type=trigger, payload=run_payload
            )
            history_ids.append(run.id)

    async with httpx.AsyncClient(timeout=20) as http:
        executor = RunExecutor(
            EngineDeps(
                session_factory=get_session_factory(),
                llm=get_llm_client(),
                http=http,
                queue=queue,
            )
        )
        for run_id in [*history_ids, *run_ids]:
            await executor.execute(run_id)
    await _backdate(history_ids)

    # Deliver the approval emails queued during the demo runs, so the links work in Mailpit.
    sent = 0
    for job in queue.named("send_email"):
        try:
            await email_service.deliver(**job)
            sent += 1
        except OSError:
            print("  (SMTP not reachable: approval emails were not sent)")
            break

    print("Demo data created.")
    print(f"  Sign in: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"  {sent} approval email(s) sent; open Mailpit to approve the waiting refund.")


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
