from typing import Any

from httpx import AsyncClient

from app.services.jobs import InMemoryJobQueue
from tests.conftest import AccountFactory
from tests.graphs import edge, graph, node

VALID = graph(
    [node("start", "trigger_webhook"), node("say", "log", {"message": "{{ trigger.body.text }}"})],
    [edge("start", "say")],
)


async def _create(
    client: AsyncClient, ws: str, headers: dict[str, str], name: str = "Flow"
) -> dict[str, Any]:
    response = await client.post(f"{ws}/workflows", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_create_save_and_validate(client: AsyncClient, accounts: AccountFactory) -> None:
    owner = await accounts.owner()
    workflow = await _create(client, owner.ws, owner.headers)
    assert workflow["issues"] == [
        {"node_id": None, "message": "Add a trigger to start the workflow"}
    ]

    incomplete = graph(
        [node("start", "trigger_manual"), node("s", "ai_summarize", {})], [edge("start", "s")]
    )
    saved = await client.patch(
        f"{owner.ws}/workflows/{workflow['id']}", json={"graph": incomplete}, headers=owner.headers
    )
    assert saved.status_code == 200
    assert saved.json()["issues"] == [{"node_id": "s", "message": "'text' is a required property"}]

    broken = await client.patch(
        f"{owner.ws}/workflows/{workflow['id']}",
        json={"graph": {"nodes": "nope"}},
        headers=owner.headers,
    )
    assert broken.status_code == 400


async def test_publish_versions_diff_and_restore(
    client: AsyncClient, accounts: AccountFactory
) -> None:
    owner = await accounts.owner()
    workflow = await _create(client, owner.ws, owner.headers)
    base = f"{owner.ws}/workflows/{workflow['id']}"

    invalid = await client.post(f"{base}/publish", json={}, headers=owner.headers)
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "workflow_invalid"
    assert invalid.json()["issues"]

    await client.patch(base, json={"graph": VALID}, headers=owner.headers)
    first = await client.post(f"{base}/publish", json={"note": "first"}, headers=owner.headers)
    assert first.json()["version"] == 1
    secret = first.json()["webhook_secret"]
    assert secret

    changed = graph(
        [
            node("start", "trigger_webhook"),
            node("say", "log", {"message": "changed"}),
            node("more", "log", {"message": "x"}),
        ],
        [edge("start", "say"), edge("say", "more")],
    )
    await client.patch(base, json={"graph": changed}, headers=owner.headers)
    second = await client.post(f"{base}/publish", json={}, headers=owner.headers)
    assert second.json() == {"version": 2, "webhook_secret": None}  # secret is kept

    versions = await client.get(f"{base}/versions", headers=owner.headers)
    assert [v["version"] for v in versions.json()] == [2, 1]

    diff = await client.get(f"{base}/versions/1/diff", headers=owner.headers)
    assert diff.json()["added_nodes"] == ["more"]
    assert diff.json()["changed_nodes"] == [{"node_id": "say", "config_fields": ["message"]}]
    assert diff.json()["added_edges"] == ["say->more:"]

    restored = await client.post(f"{base}/versions/1/restore", headers=owner.headers)
    assert restored.json()["draft_graph"] == VALID
    assert restored.json()["published_version"] == 2


async def test_schedule_publish_sets_next_run(
    client: AsyncClient, accounts: AccountFactory
) -> None:
    owner = await accounts.owner()
    workflow = await _create(client, owner.ws, owner.headers)
    base = f"{owner.ws}/workflows/{workflow['id']}"
    scheduled = graph(
        [
            node("tick", "trigger_schedule", {"cron": "0 9 * * *", "timezone": "Asia/Ho_Chi_Minh"}),
            node("say", "log", {"message": "hi"}),
        ],
        [edge("tick", "say")],
    )
    await client.patch(base, json={"graph": scheduled}, headers=owner.headers)
    await client.post(f"{base}/publish", json={}, headers=owner.headers)
    detail = (await client.get(base, headers=owner.headers)).json()
    assert detail["schedule_cron"] == "0 9 * * *"
    assert detail["next_run_at"].endswith(("02:00:00Z", "02:00:00+00:00"))  # 09:00 in UTC+7

    paused = await client.post(f"{base}/activation", json={"active": False}, headers=owner.headers)
    assert paused.json()["is_active"] is False
    audit = await client.get(f"{owner.ws}/audit-logs", headers=owner.headers)
    actions = [entry["action"] for entry in audit.json()]
    assert "workflow.paused" in actions


async def test_test_run_queues_execution(
    client: AsyncClient, accounts: AccountFactory, queue: InMemoryJobQueue
) -> None:
    owner = await accounts.owner()
    workflow = await _create(client, owner.ws, owner.headers)
    base = f"{owner.ws}/workflows/{workflow['id']}"
    await client.patch(base, json={"graph": VALID}, headers=owner.headers)

    published_only = await client.post(
        f"{base}/runs", json={"payload": {}, "use_draft": False}, headers=owner.headers
    )
    assert published_only.status_code == 400

    run = await client.post(
        f"{base}/runs", json={"payload": {"body": {"text": "hi"}}}, headers=owner.headers
    )
    assert run.status_code == 202
    assert run.json()["status"] == "queued"
    assert queue.named("execute_run") == [{"run_id": run.json()["id"]}]


async def test_templates_and_import_export(client: AsyncClient, accounts: AccountFactory) -> None:
    owner = await accounts.owner()
    templates = (await client.get("/api/v1/templates")).json()
    assert {t["id"] for t in templates} == {"support-triage", "lead-qualification", "daily-digest"}

    from_template = await client.post(
        f"{owner.ws}/workflows",
        json={"name": "ignored", "template_id": "support-triage"},
        headers=owner.headers,
    )
    assert from_template.status_code == 201
    assert from_template.json()["name"] == "Support ticket triage"
    assert from_template.json()["issues"] == []

    exported = await client.get(
        f"{owner.ws}/workflows/{from_template.json()['id']}/export", headers=owner.headers
    )
    assert exported.json()["format"] == "flowforge.workflow/v1"

    imported = await client.post(
        f"{owner.ws}/workflows/import", json={"data": exported.json()}, headers=owner.headers
    )
    assert imported.status_code == 201
    assert imported.json()["draft_graph"] == from_template.json()["draft_graph"]

    bad = await client.post(
        f"{owner.ws}/workflows/import", json={"data": {"x": 1}}, headers=owner.headers
    )
    assert bad.status_code == 400


async def test_every_template_is_valid(client: AsyncClient) -> None:
    from app.services.workflows import list_templates, validate

    for template in list_templates():
        assert validate(template["graph"]) == [], template["id"]


async def test_free_plan_workflow_limit(client: AsyncClient, accounts: AccountFactory) -> None:
    owner = await accounts.owner()
    for i in range(5):
        await _create(client, owner.ws, owner.headers, f"Flow {i}")
    response = await client.post(
        f"{owner.ws}/workflows", json={"name": "Sixth"}, headers=owner.headers
    )
    assert response.status_code == 402


async def test_node_type_catalog(client: AsyncClient) -> None:
    types = {t["type"]: t for t in (await client.get("/api/v1/node-types")).json()}
    assert len(types) == 22
    assert types["condition"]["static_handles"] == ["true", "false"]
    assert types["ai_classify"]["dynamic_handles_key"] == "labels"
    assert (
        types["slack_message"]["config_schema"]["properties"]["credential_id"]["x-ui"]
        == "credential"
    )


async def test_viewer_cannot_edit_and_isolation(
    client: AsyncClient, accounts: AccountFactory
) -> None:
    from app.core.permissions import Role

    owner = await accounts.owner()
    viewer = await accounts.member(owner, Role.VIEWER)
    other = await accounts.owner("Other")
    workflow = await _create(client, owner.ws, owner.headers)

    blocked = await client.patch(
        f"{owner.ws}/workflows/{workflow['id']}", json={"name": "x"}, headers=viewer.headers
    )
    assert blocked.status_code == 403
    assert (
        await client.get(f"{owner.ws}/workflows/{workflow['id']}", headers=viewer.headers)
    ).status_code == 200

    cross = await client.get(f"{other.ws}/workflows/{workflow['id']}", headers=other.headers)
    assert cross.status_code == 404
    foreign_ws = await client.get(f"{owner.ws}/workflows", headers=other.headers)
    assert foreign_ws.status_code == 404
