import json
import uuid

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.permissions import Role
from app.engine.executor import RunExecutor
from app.models import Credential, RunStatus
from tests.conftest import Account, AccountFactory
from tests.graphs import edge, graph, load_run, make_run, make_workflow, node

SLACK_URL = "https://hooks.slack.com/services/T000/B000/XXXX"


async def _credential(
    client: AsyncClient, owner: Account, name: str, type_name: str, data: dict[str, str]
) -> str:
    response = await client.post(
        f"{owner.ws}/credentials",
        json={"name": name, "type": type_name, "data": data},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_credentials_are_write_only_and_encrypted(
    client: AsyncClient, accounts: AccountFactory, session: AsyncSession
) -> None:
    owner = await accounts.owner()
    credential_id = await _credential(
        client, owner, "Team Slack", "slack_webhook", {"url": SLACK_URL}
    )

    listed = await client.get(f"{owner.ws}/credentials", headers=owner.headers)
    assert listed.json()[0].keys() == {"id", "name", "type", "created_at", "updated_at"}
    stored = await session.scalar(select(Credential))
    assert stored is not None and SLACK_URL not in stored.encrypted_data

    duplicate = await client.post(
        f"{owner.ws}/credentials",
        json={"name": "Team Slack", "type": "slack_webhook", "data": {"url": SLACK_URL}},
        headers=owner.headers,
    )
    assert duplicate.status_code == 409
    invalid = await client.post(
        f"{owner.ws}/credentials",
        json={"name": "Bad", "type": "slack_webhook", "data": {"url": "https://evil.example"}},
        headers=owner.headers,
    )
    assert invalid.status_code == 400

    member = await accounts.member(owner, Role.MEMBER)
    forbidden = await client.delete(
        f"{owner.ws}/credentials/{credential_id}", headers=member.headers
    )
    assert forbidden.status_code == 403

    renamed = await client.patch(
        f"{owner.ws}/credentials/{credential_id}", json={"name": "Alerts"}, headers=owner.headers
    )
    assert renamed.json()["name"] == "Alerts"
    types = (await client.get("/api/v1/credential-types")).json()
    assert {t["type"] for t in types} >= {"slack_webhook", "telegram_bot", "google_service_account"}


@respx.mock
async def test_slack_and_telegram_nodes_use_credentials(
    client: AsyncClient,
    accounts: AccountFactory,
    session: AsyncSession,
    executor: RunExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "allow_private_network_requests", True)
    owner = await accounts.owner()
    slack_id = await _credential(client, owner, "Slack", "slack_webhook", {"url": SLACK_URL})
    bot_id = await _credential(client, owner, "Bot", "telegram_bot", {"token": "123:ABC"})
    slack = respx.post(SLACK_URL).mock(return_value=httpx.Response(200, text="ok"))
    telegram = respx.post("https://api.telegram.org/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})
    )

    workflow = await make_workflow(
        session,
        owner.workspace,
        graph(
            [
                node("t", "trigger_manual"),
                node(
                    "slack",
                    "slack_message",
                    {"credential_id": slack_id, "text": "Order {{ trigger.id }}"},
                ),
                node(
                    "tg",
                    "telegram_message",
                    {"credential_id": bot_id, "chat_id": "-100", "text": "hi"},
                ),
            ],
            [edge("t", "slack"), edge("t", "tg")],
        ),
    )
    run = await make_run(session, workflow, {"id": 7})
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)

    assert run.status == RunStatus.SUCCEEDED
    assert json.loads(slack.calls.last.request.content) == {"text": "Order 7"}
    assert steps["tg"].output == {"message_id": 42}
    assert telegram.called
    assert SLACK_URL not in json.dumps(steps["slack"].input)


@respx.mock
async def test_google_sheets_append(
    client: AsyncClient,
    accounts: AccountFactory,
    session: AsyncSession,
    executor: RunExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "allow_private_network_requests", True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    key_json = json.dumps({"client_email": "bot@proj.iam.gserviceaccount.com", "private_key": pem})
    owner = await accounts.owner()
    cred_id = await _credential(
        client, owner, "Sheets", "google_service_account", {"service_account_json": key_json}
    )

    token = respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
    )
    append = respx.post(
        url__regex=r"https://sheets\.googleapis\.com/v4/spreadsheets/SHEET123/values/.*:append"
    ).mock(return_value=httpx.Response(200, json={"updates": {"updatedRange": "Leads!A2:B2"}}))
    workflow = await make_workflow(
        session,
        owner.workspace,
        graph(
            [
                node("t", "trigger_manual"),
                node(
                    "row",
                    "google_sheets_append",
                    {
                        "credential_id": cred_id,
                        "spreadsheet_id": "SHEET123",
                        "range": "Leads!A1",
                        "values": ["{{ trigger.email }}", "new"],
                    },
                ),
            ],
            [edge("t", "row")],
        ),
    )
    run = await make_run(session, workflow, {"email": "ana@example.com"})
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)

    assert run.status == RunStatus.SUCCEEDED, steps["row"].error
    assert steps["row"].output == {
        "updated_range": "Leads!A2:B2",
        "values": ["ana@example.com", "new"],
    }
    assert token.called
    assert append.calls.last.request.headers["authorization"] == "Bearer ya29.token"
    assert json.loads(append.calls.last.request.content) == {"values": [["ana@example.com", "new"]]}


async def test_credentials_from_another_workspace_cannot_be_used(
    client: AsyncClient, accounts: AccountFactory, session: AsyncSession, executor: RunExecutor
) -> None:
    alice = await accounts.owner("Alice")
    bob = await accounts.owner("Bob")
    alice_cred = await _credential(client, alice, "Slack", "slack_webhook", {"url": SLACK_URL})
    workflow = await make_workflow(
        session,
        bob.workspace,
        graph(
            [
                node("t", "trigger_manual"),
                node("slack", "slack_message", {"credential_id": alice_cred, "text": "hi"}),
            ],
            [edge("t", "slack")],
        ),
    )
    run = await make_run(session, workflow)
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)
    assert run.status == RunStatus.FAILED
    assert "no longer exists" in (steps["slack"].error or "")


async def test_runs_api_list_detail_cancel_retry_and_dashboard(
    client: AsyncClient, accounts: AccountFactory, session: AsyncSession, executor: RunExecutor
) -> None:
    owner = await accounts.owner()
    workflow = await make_workflow(
        session,
        owner.workspace,
        graph(
            [node("t", "trigger_manual"), node("bad", "log", {"message": "{{ trigger.nope }}"})],
            [edge("t", "bad")],
        ),
        name="Broken",
    )
    run = await make_run(session, workflow)
    await executor.execute(run.id)

    listing = await client.get(
        f"{owner.ws}/runs", params={"status": "failed"}, headers=owner.headers
    )
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["workflow_name"] == "Broken"

    detail = await client.get(f"{owner.ws}/runs/{run.id}", headers=owner.headers)
    steps = {s["node_id"]: s for s in detail.json()["steps"]}
    assert steps["bad"]["status"] == "failed"
    assert "not defined" in steps["bad"]["error"]

    finished_cancel = await client.post(f"{owner.ws}/runs/{run.id}/cancel", headers=owner.headers)
    assert finished_cancel.status_code == 400

    retry = await client.post(
        f"{owner.ws}/runs/{run.id}/retry", json={"from_failed_step": True}, headers=owner.headers
    )
    assert retry.status_code == 202
    assert retry.json()["retry_of_id"] == str(run.id)
    assert retry.json()["trigger_type"] == "retry"

    dashboard = await client.get(f"{owner.ws}/dashboard", params={"days": 7}, headers=owner.headers)
    body = dashboard.json()
    assert body["total_runs"] == 2
    assert body["failed"] == 1
    assert body["failing_workflows"][0]["name"] == "Broken"
    assert len(body["daily"]) == 8

    other = await accounts.owner("Other")
    assert (await client.get(f"{other.ws}/runs/{run.id}", headers=other.headers)).status_code == 404
    assert (
        await client.get(f"{owner.ws}/runs/{uuid.uuid4()}", headers=owner.headers)
    ).status_code == 404
