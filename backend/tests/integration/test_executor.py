import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.llm import ChatMessage, FakeLLMClient
from app.engine.executor import Outcome, RunExecutor
from app.engine.nodes.base import (
    NodeCategory,
    NodeContext,
    NodeExecutionError,
    NodeResult,
    NodeType,
)
from app.engine.nodes.registry import registry
from app.models import Approval, ApprovalStatus, LlmUsage, Run, RunStatus, StepStatus
from app.services import runs as run_service
from app.services.jobs import InMemoryJobQueue
from tests.conftest import AccountFactory
from tests.graphs import edge, graph, load_run, make_run, make_workflow, node

API = "https://api.example.com"


@pytest.fixture
def allow_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "allow_private_network_requests", True)


async def _run(
    session: AsyncSession,
    executor: RunExecutor,
    accounts: AccountFactory,
    workflow_graph: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> tuple[Run, dict[str, Any]]:
    account = await accounts.owner()
    workflow = await make_workflow(session, account.workspace, workflow_graph)
    run = await make_run(session, workflow, payload)
    await executor.execute(run.id)
    return await load_run(session, run.id)


async def test_linear_workflow_passes_data_between_steps(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node("shape", "transform", {"output": {"name": "{{ trigger.name | upper }}"}}),
                node("say", "log", {"message": "Hello {{ steps.shape.output.name }}"}),
            ],
            [edge("start", "shape"), edge("shape", "say")],
        ),
        {"name": "ana"},
    )
    assert run.status == RunStatus.SUCCEEDED
    assert steps["start"].output == {"name": "ana"}
    assert steps["say"].output["message"] == "Hello ANA"
    assert steps["say"].input == {"message": "Hello ANA"}
    assert run.started_at is not None and run.finished_at is not None


async def test_condition_runs_one_branch_and_skips_the_other(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "big",
                    "condition",
                    {"left": "{{ trigger.amount }}", "operator": "greater_than", "right": "100"},
                ),
                node("yes", "log", {"message": "big"}),
                node("yes_after", "log", {"message": "still big"}),
                node("no", "log", {"message": "small"}),
                node("done", "merge"),
            ],
            [
                edge("start", "big"),
                edge("big", "yes", "true"),
                edge("yes", "yes_after"),
                edge("big", "no", "false"),
                edge("yes_after", "done"),
                edge("no", "done"),
            ],
        ),
        {"amount": 50},
    )
    assert run.status == RunStatus.SUCCEEDED
    assert steps["big"].branch == "false"
    assert steps["yes"].status == StepStatus.SKIPPED
    assert steps["yes_after"].status == StepStatus.SKIPPED
    assert steps["no"].status == StepStatus.SUCCEEDED
    assert steps["done"].status == StepStatus.SUCCEEDED
    assert steps["done"].output == {"no": {"message": "small", "level": "info"}}


async def test_independent_branches_run_in_parallel(
    session: AsyncSession,
    executor: RunExecutor,
    accounts: AccountFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_type = registry.get("log")
    assert log_type is not None
    original = log_type.execute

    async def slow(ctx: NodeContext) -> NodeResult:
        await asyncio.sleep(0.5)
        return await original(ctx)

    monkeypatch.setattr(log_type, "execute", slow)
    account = await accounts.owner()
    workflow = await make_workflow(
        session,
        account.workspace,
        graph(
            [node("start", "trigger_manual")]
            + [node(f"b{i}", "log", {"message": str(i)}) for i in range(4)],
            [edge("start", f"b{i}") for i in range(4)],
        ),
    )
    pending = await make_run(session, workflow, None)
    # Time only the execution, not the account and workflow setup above.
    started = asyncio.get_running_loop().time()
    await executor.execute(pending.id)
    elapsed = asyncio.get_running_loop().time() - started
    run, _ = await load_run(session, pending.id)
    assert run.status == RunStatus.SUCCEEDED
    assert elapsed < 1.5, f"4 steps of 0.5s took {elapsed:.2f}s, so they did not overlap"


class FlakyNode(NodeType):
    type = "test_flaky"
    label = "Flaky"
    description = "Fails a given number of times, then succeeds"
    category = NodeCategory.DATA
    failures_left = 0
    calls = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        FlakyNode.calls += 1
        if FlakyNode.failures_left > 0:
            FlakyNode.failures_left -= 1
            raise NodeExecutionError("temporary problem")
        return NodeResult(output={"ok": True})


class SlowNode(NodeType):
    type = "test_slow"
    label = "Slow"
    description = "Sleeps longer than its timeout"
    category = NodeCategory.DATA

    async def execute(self, ctx: NodeContext) -> NodeResult:
        await asyncio.sleep(5)
        return NodeResult(output={})


@pytest.fixture
def test_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    types = dict(registry._types)
    types["test_flaky"] = FlakyNode()
    types["test_slow"] = SlowNode()
    monkeypatch.setattr(registry, "_types", types)
    FlakyNode.calls = 0


async def test_retries_with_backoff_then_succeeds(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory, test_nodes: None
) -> None:
    FlakyNode.failures_left = 2
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node("flaky", "test_flaky", settings={"retries": 3, "retry_delay_seconds": 0.01}),
            ],
            [edge("start", "flaky")],
        ),
    )
    assert run.status == RunStatus.SUCCEEDED
    assert steps["flaky"].attempt == 3
    assert FlakyNode.calls == 3


async def test_exhausted_retries_fail_the_run_and_stop_downstream(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory, test_nodes: None
) -> None:
    FlakyNode.failures_left = 10
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node("flaky", "test_flaky", settings={"retries": 1, "retry_delay_seconds": 0}),
                node("after", "log", {"message": "never"}),
            ],
            [edge("start", "flaky"), edge("flaky", "after")],
        ),
    )
    assert run.status == RunStatus.FAILED
    assert "temporary problem" in (run.error or "")
    assert steps["flaky"].status == StepStatus.FAILED
    assert steps["flaky"].attempt == 2
    assert "after" not in steps


async def test_timeout_and_continue_on_error(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory, test_nodes: None
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "slow", "test_slow", settings={"timeout_seconds": 1, "continue_on_error": True}
                ),
                node("after", "log", {"message": "error was {{ steps.slow.output.error }}"}),
            ],
            [edge("start", "slow"), edge("slow", "after")],
        ),
    )
    assert run.status == RunStatus.SUCCEEDED
    assert steps["slow"].error == "Timed out after 1s"
    assert steps["after"].output["message"] == "error was Timed out after 1s"


async def test_expression_errors_fail_without_retrying(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node("say", "log", {"message": "{{ trigger.missing }}"}, settings={"retries": 3}),
            ],
            [edge("start", "say")],
        ),
    )
    assert run.status == RunStatus.FAILED
    assert steps["say"].attempt == 0
    assert "not defined" in (steps["say"].error or "")


async def test_ai_nodes_route_and_record_usage(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "classify",
                    "ai_classify",
                    {"text": "{{ trigger.message }}", "labels": ["refund", "bug", "other"]},
                ),
                node(
                    "extract",
                    "ai_extract",
                    {"text": "{{ trigger.message }}", "fields": {"order": "Order number"}},
                ),
                node("summary", "ai_summarize", {"text": "{{ trigger.message }}"}),
                node("other", "log", {"message": "other"}),
            ],
            [
                edge("start", "classify"),
                edge("classify", "extract", "refund"),
                edge("extract", "summary"),
                edge("classify", "other", "other"),
            ],
        ),
        {"message": "I want a refund. Order: A-1001, it arrived broken."},
    )
    assert run.status == RunStatus.SUCCEEDED
    assert steps["classify"].branch == "refund"
    assert steps["extract"].output == {"order": "A-1001"}
    assert steps["summary"].output["summary"] == "I want a refund."
    assert steps["other"].status == StepStatus.SKIPPED
    usage_rows = list(await session.scalars(select(LlmUsage)))
    assert {u.kind for u in usage_rows} == {"ai_classify", "ai_extract", "ai_summarize"}


async def test_unknown_classifier_label_is_an_error(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory, llm: FakeLLMClient
) -> None:
    def responder(messages: list[ChatMessage]) -> str:
        return json.dumps({"label": "banana"})

    llm.responder = responder
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node("c", "ai_classify", {"text": "x", "labels": ["a", "b"]}),
            ],
            [edge("start", "c")],
        ),
    )
    assert run.status == RunStatus.FAILED
    assert "unknown label 'banana'" in (steps["c"].error or "")


async def test_delay_pauses_and_resumes(
    session: AsyncSession,
    executor: RunExecutor,
    accounts: AccountFactory,
    queue: InMemoryJobQueue,
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node("wait", "delay", {"seconds": 3600}),
                node("after", "log", {"message": "later"}),
            ],
            [edge("start", "wait"), edge("wait", "after")],
        ),
    )
    assert run.status == RunStatus.WAITING
    assert steps["wait"].status == StepStatus.WAITING
    wakeup = queue.named("execute_run")[-1]
    assert wakeup["run_id"] == str(run.id)
    assert wakeup["_defer_until"] == steps["wait"].resume_at

    # Still waiting if woken early.
    assert await executor.execute(run.id) == Outcome.WAITING

    steps["wait"].resume_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await executor.execute(run.id) == Outcome.FINISHED
    run, steps = await load_run(session, run.id)
    assert run.status == RunStatus.SUCCEEDED
    assert steps["after"].status == StepStatus.SUCCEEDED


@pytest.mark.parametrize(
    ("decision", "branch"),
    [
        (ApprovalStatus.APPROVED, "approved"),
        (ApprovalStatus.REJECTED, "rejected"),
        (ApprovalStatus.EXPIRED, "rejected"),
    ],
)
async def test_approval_waits_for_a_decision(
    session: AsyncSession,
    executor: RunExecutor,
    accounts: AccountFactory,
    queue: InMemoryJobQueue,
    decision: ApprovalStatus,
    branch: str,
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "ok",
                    "approval",
                    {"approvers": ["Boss@Example.com"], "message": "Refund {{ trigger.amount }}?"},
                ),
                node("yes", "log", {"message": "approved"}),
                node("no", "log", {"message": "rejected"}),
            ],
            [edge("start", "ok"), edge("ok", "yes", "approved"), edge("ok", "no", "rejected")],
        ),
        {"amount": 99},
    )
    assert run.status == RunStatus.WAITING
    approval = await session.scalar(select(Approval))
    assert approval is not None
    assert approval.approvers == ["boss@example.com"]
    assert approval.message == "Refund 99?"
    email = queue.named("send_email")[0]
    assert email["to"] == "boss@example.com"
    assert "/approvals/" in email["text"]

    assert await executor.execute(run.id) == Outcome.WAITING

    approval.status = decision
    approval.decided_by = "Boss"
    await session.commit()
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)
    assert run.status == RunStatus.SUCCEEDED
    assert steps["ok"].branch == branch
    taken, skipped = ("yes", "no") if branch == "approved" else ("no", "yes")
    assert steps[taken].status == StepStatus.SUCCEEDED
    assert steps[skipped].status == StepStatus.SKIPPED


async def test_for_each_runs_a_child_workflow_per_item(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    account = await accounts.owner()
    child = await make_workflow(
        session,
        account.workspace,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "double",
                    "transform",
                    {"output": {"value": "{{ trigger.item * 2 }}", "index": "{{ trigger.index }}"}},
                ),
            ],
            [edge("start", "double")],
        ),
        name="Double",
        publish=True,
    )
    parent = await make_workflow(
        session,
        account.workspace,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "each",
                    "for_each",
                    {
                        "items": "{{ trigger.numbers }}",
                        "workflow_id": str(child.id),
                        "concurrency": 2,
                    },
                ),
            ],
            [edge("start", "each")],
        ),
    )
    run = await make_run(session, parent, {"numbers": [1, 2, 3]})
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)

    assert run.status == RunStatus.SUCCEEDED
    assert steps["each"].output == {
        "results": [
            {"double": {"value": 2, "index": 0}},
            {"double": {"value": 4, "index": 1}},
            {"double": {"value": 6, "index": 2}},
        ],
        "count": 3,
    }
    children = list(await session.scalars(select(Run).where(Run.parent_run_id == run.id)))
    assert len(children) == 3
    assert all(c.status == RunStatus.SUCCEEDED and c.depth == 1 for c in children)


async def test_sub_workflow_failure_and_unpublished_workflow(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    account = await accounts.owner()
    draft_only = await make_workflow(
        session, account.workspace, graph([node("start", "trigger_manual")], [])
    )
    parent = await make_workflow(
        session,
        account.workspace,
        graph(
            [
                node("start", "trigger_manual"),
                node("sub", "sub_workflow", {"workflow_id": str(draft_only.id)}),
            ],
            [edge("start", "sub")],
        ),
    )
    run = await make_run(session, parent)
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)
    assert run.status == RunStatus.FAILED
    assert "not published" in (steps["sub"].error or "")


async def test_child_workflows_cannot_pause(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    account = await accounts.owner()
    child = await make_workflow(
        session,
        account.workspace,
        graph(
            [node("start", "trigger_manual"), node("wait", "delay", {"seconds": 60})],
            [edge("start", "wait")],
        ),
        publish=True,
    )
    parent = await make_workflow(
        session,
        account.workspace,
        graph(
            [
                node("start", "trigger_manual"),
                node("sub", "sub_workflow", {"workflow_id": str(child.id)}),
            ],
            [edge("start", "sub")],
        ),
    )
    run = await make_run(session, parent)
    await executor.execute(run.id)
    run, steps = await load_run(session, run.id)
    assert run.status == RunStatus.FAILED
    assert "cannot pause" in (steps["sub"].error or "")


async def test_cancel_and_retry_from_failed_step(
    session: AsyncSession,
    executor: RunExecutor,
    accounts: AccountFactory,
    queue: InMemoryJobQueue,
    test_nodes: None,
) -> None:
    account = await accounts.owner()
    workflow = await make_workflow(
        session,
        account.workspace,
        graph(
            [
                node("start", "trigger_manual"),
                node("first", "log", {"message": "first"}),
                node("flaky", "test_flaky"),
                node("last", "log", {"message": "{{ steps.flaky.output.ok }}"}),
            ],
            [edge("start", "first"), edge("first", "flaky"), edge("flaky", "last")],
        ),
    )
    FlakyNode.failures_left = 1
    run = await make_run(session, workflow)
    await executor.execute(run.id)
    failed, _ = await load_run(session, run.id)
    assert failed.status == RunStatus.FAILED

    retry = await run_service.retry_run(
        session, queue, account.workspace, failed, from_failed_step=True, created_by_id=None
    )
    calls_before = FlakyNode.calls
    await executor.execute(retry.id)
    retried, steps = await load_run(session, retry.id)
    assert retried.status == RunStatus.SUCCEEDED
    assert retried.retry_of_id == failed.id
    assert steps["first"].attempt == 1  # copied, not executed again
    assert FlakyNode.calls == calls_before + 1
    assert steps["last"].output["message"] is True  # a lone expression keeps its native type

    waiting_run = await make_run(session, workflow)
    waiting_run.status = RunStatus.WAITING
    await session.commit()
    cancelled = await run_service.cancel_run(session, waiting_run)
    assert cancelled.status == RunStatus.CANCELLED
    assert await executor.execute(waiting_run.id) == Outcome.FINISHED


async def test_concurrency_limit_defers_new_runs(
    session: AsyncSession,
    executor: RunExecutor,
    accounts: AccountFactory,
    queue: InMemoryJobQueue,
) -> None:
    account = await accounts.owner()
    workflow = await make_workflow(
        session, account.workspace, graph([node("start", "trigger_manual")], [])
    )
    for _ in range(2):  # Free plan allows 2 concurrent runs
        busy = await make_run(session, workflow)
        busy.status = RunStatus.RUNNING
    await session.commit()

    run = await make_run(session, workflow)
    assert await executor.execute(run.id) == Outcome.DEFERRED
    assert queue.named("execute_run")[-1] == {"run_id": str(run.id), "_defer_by": 5}
    run, _ = await load_run(session, run.id)
    assert run.status == RunStatus.QUEUED


@respx.mock
async def test_http_request_node_and_ssrf_protection(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory, allow_private: None
) -> None:
    route = respx.post(f"{API}/orders").mock(return_value=httpx.Response(201, json={"id": 7}))
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "call",
                    "http_request",
                    {
                        "method": "POST",
                        "url": f"{API}/orders",
                        "body": {"sku": "{{ trigger.sku }}"},
                        "headers": {"X-Test": "1"},
                    },
                ),
            ],
            [edge("start", "call")],
        ),
        {"sku": "COFFEE"},
    )
    assert run.status == RunStatus.SUCCEEDED
    assert steps["call"].output["body"] == {"id": 7}
    assert json.loads(route.calls.last.request.content) == {"sku": "COFFEE"}
    assert route.calls.last.request.headers["x-test"] == "1"


async def test_private_addresses_are_blocked(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory
) -> None:
    run, steps = await _run(
        session,
        executor,
        accounts,
        graph(
            [
                node("start", "trigger_manual"),
                node(
                    "call",
                    "http_request",
                    {"method": "GET", "url": "http://169.254.169.254/latest/meta-data"},
                    settings={"retries": 2},
                ),
            ],
            [edge("start", "call")],
        ),
    )
    assert run.status == RunStatus.FAILED
    assert "private or internal" in (steps["call"].error or "")
    assert steps["call"].attempt == 1


async def test_agent_calls_tools(
    session: AsyncSession, executor: RunExecutor, accounts: AccountFactory, allow_private: None
) -> None:
    with respx.mock:
        respx.get(f"{API}/weather").mock(return_value=httpx.Response(200, json={"temp": 21}))
        run, steps = await _run(
            session,
            executor,
            accounts,
            graph(
                [
                    node("start", "trigger_manual"),
                    node(
                        "agent",
                        "ai_agent",
                        {
                            "goal": "What is the weather?",
                            "tools": [
                                {
                                    "name": "weather",
                                    "description": "Current weather",
                                    "method": "GET",
                                    "url": f"{API}/weather",
                                }
                            ],
                        },
                    ),
                ],
                [edge("start", "agent")],
            ),
        )
    assert run.status == RunStatus.SUCCEEDED
    output = steps["agent"].output
    assert output["tool_calls"][0]["result"] == {"status": 200, "body": {"temp": 21}}
    assert "21" in output["answer"]
