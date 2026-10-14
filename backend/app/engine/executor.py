"""The run loop (see docs/ARCHITECTURE.md §5 and docs/adr/0002).

State lives in `step_runs`. Each call to `RunExecutor.execute` rebuilds the state from the
database, runs every node that is ready (in parallel), and stops when nothing is ready: the run
then is succeeded, failed, cancelled or waiting. Waiting runs are continued by calling
`execute` again later (after a delay, or when an approval is decided).
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import realtime
from app.core.crypto import decrypt_json
from app.core.errors import ServiceUnavailableError
from app.core.llm import LLMClient
from app.core.metrics import RUNS_FINISHED_TOTAL, STEP_DURATION
from app.core.redis import get_redis
from app.engine.context import build_context
from app.engine.expressions import ExpressionError, render_value
from app.engine.graph import Graph, GraphError, Node
from app.engine.nodes.base import NodeContext, NodeExecutionError, NodeResult
from app.engine.nodes.registry import registry
from app.models import (
    Credential,
    Run,
    RunStatus,
    StepRun,
    StepStatus,
    TriggerType,
    Workflow,
    WorkflowVersion,
    Workspace,
)
from app.services import plans
from app.services.jobs import JobQueue
from app.services.usage import record_llm_usage

logger = structlog.get_logger(__name__)

MAX_CHILD_DEPTH = 3
CONCURRENCY_RETRY_SECONDS = 5
LOCK_RETRY_SECONDS = 3


class Outcome(StrEnum):
    FINISHED = "finished"  # terminal status reached (or run missing)
    WAITING = "waiting"
    DEFERRED = "deferred"  # try again later (concurrency limit or run locked)


@dataclass
class EngineDeps:
    session_factory: async_sessionmaker[AsyncSession]
    llm: LLMClient
    http: httpx.AsyncClient
    queue: JobQueue


class StepFailedError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _json_safe(value: Any) -> Any:
    """Make node output storable as JSONB (datetimes, UUIDs, sets...)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime | uuid.UUID):
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


async def publish_run(run: Run) -> None:
    await realtime.publish(
        realtime.workspace_channel(run.workspace_id),
        "run.updated",
        {
            "id": run.id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "parent_run_id": run.parent_run_id,
            "error": run.error,
        },
    )


async def publish_step(run: Run, step: StepRun) -> None:
    await realtime.publish(
        realtime.workspace_channel(run.workspace_id),
        "step.updated",
        {
            "run_id": run.id,
            "workflow_id": run.workflow_id,
            "node_id": step.node_id,
            "status": step.status,
            "branch": step.branch,
            "error": step.error,
            "duration_ms": step.duration_ms,
        },
    )


@asynccontextmanager
async def run_lock(run_id: uuid.UUID, ttl_seconds: int) -> AsyncIterator[bool]:
    """Only one worker may advance a run at a time."""
    redis = get_redis()
    key = f"run_lock:{run_id}"
    token = uuid.uuid4().hex
    acquired = bool(await redis.set(key, token, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired and await redis.get(key) == token:
            await redis.delete(key)


class RunExecutor:
    def __init__(self, deps: EngineDeps, lock_ttl_seconds: int = 900) -> None:
        self.deps = deps
        self.lock_ttl_seconds = lock_ttl_seconds

    # --- public API --------------------------------------------------------------------------

    async def execute(self, run_id: uuid.UUID, *, inline: bool = False) -> Outcome:
        async with run_lock(run_id, self.lock_ttl_seconds) as acquired:
            if not acquired:
                if not inline:
                    await self.deps.queue.enqueue(
                        "execute_run", run_id=str(run_id), _defer_by=LOCK_RETRY_SECONDS
                    )
                return Outcome.DEFERRED
            return await self._execute(run_id, inline=inline)

    # --- the loop ----------------------------------------------------------------------------

    async def _execute(self, run_id: uuid.UUID, *, inline: bool) -> Outcome:
        async with self.deps.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None or RunStatus(run.status).is_terminal:
                return Outcome.FINISHED
            workflow = await session.get(Workflow, run.workflow_id)
            workflow_name = workflow.name if workflow else "Deleted workflow"

            if run.status == RunStatus.QUEUED and run.parent_run_id is None and not inline:
                workspace = await session.get(Workspace, run.workspace_id)
                limit = plans.plan_for(workspace).max_concurrent_runs if workspace else 1
                if await plans.count_running(session, run.workspace_id) >= limit:
                    await self.deps.queue.enqueue(
                        "execute_run", run_id=str(run.id), _defer_by=CONCURRENCY_RETRY_SECONDS
                    )
                    return Outcome.DEFERRED

            try:
                graph = Graph.parse(run.graph)
                trigger = graph.trigger()
            except GraphError as exc:
                await self._finish(session, run, RunStatus.FAILED, f"Invalid workflow: {exc}")
                return Outcome.FINISHED

            if run.status != RunStatus.RUNNING:
                run.status = RunStatus.RUNNING
                run.started_at = run.started_at or _now()
                await session.commit()
                await publish_run(run)

            steps = await self._load_steps(session, run.id)
            if trigger.id not in steps:
                steps[trigger.id] = await self._save_step(
                    session,
                    run,
                    StepRun(
                        run_id=run.id,
                        workspace_id=run.workspace_id,
                        node_id=trigger.id,
                        node_type=trigger.type,
                        status=StepStatus.SUCCEEDED,
                        attempt=1,
                        output=run.trigger_payload,
                        started_at=_now(),
                        finished_at=_now(),
                        duration_ms=0,
                    ),
                )

            while True:
                await session.refresh(run, ["cancel_requested"])
                if run.cancel_requested:
                    await self._finish(session, run, RunStatus.CANCELLED, "Cancelled by a user")
                    return Outcome.FINISHED

                progressed = await self._resume_waiting(session, run, graph, workflow_name, steps)
                progressed |= await self._skip_unreachable(session, run, graph, steps)
                ready = self._ready_nodes(graph, steps)

                if ready:
                    context = build_context(run, workflow_name, steps)
                    results = await asyncio.gather(
                        *(
                            self._run_step(run, node, graph, workflow_name, context, steps)
                            for node in ready
                        ),
                        return_exceptions=True,
                    )
                    steps = await self._load_steps(session, run.id)
                    failures = [r for r in results if isinstance(r, BaseException)]
                    if failures:
                        error = failures[0]
                        message = str(error) if isinstance(error, StepFailedError) else repr(error)
                        if not isinstance(error, StepFailedError):
                            logger.error("step_crashed", run_id=str(run.id), error=message)
                        await self._finish(session, run, RunStatus.FAILED, message)
                        return Outcome.FINISHED
                    continue
                if progressed:
                    continue

                waiting = [s for s in steps.values() if s.status == StepStatus.WAITING]
                if waiting:
                    run.status = RunStatus.WAITING
                    await session.commit()
                    await publish_run(run)
                    if not inline:
                        await self._schedule_wakeups(run, waiting)
                    return Outcome.WAITING

                await self._finish(session, run, RunStatus.SUCCEEDED, None)
                return Outcome.FINISHED

    # --- state helpers -----------------------------------------------------------------------

    @staticmethod
    async def _load_steps(session: AsyncSession, run_id: uuid.UUID) -> dict[str, StepRun]:
        # Steps are written by other sessions (one per parallel step); refresh them in place.
        rows = await session.scalars(
            select(StepRun)
            .where(StepRun.run_id == run_id)
            .execution_options(populate_existing=True)
        )
        return {step.node_id: step for step in rows}

    @staticmethod
    def _edge_active(steps: dict[str, StepRun], source: str, handle: str | None) -> bool:
        parent = steps.get(source)
        if parent is None or parent.status != StepStatus.SUCCEEDED:
            return False
        return handle is None or handle == parent.branch

    def _ready_nodes(self, graph: Graph, steps: dict[str, StepRun]) -> list[Node]:
        ready = []
        for node in graph.nodes.values():
            if node.id in steps:
                continue
            incoming = graph.incoming(node.id)
            if not incoming:
                continue
            parents = [steps.get(edge.source) for edge in incoming]
            if any(
                p is None or p.status not in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
                for p in parents
            ):
                continue
            if any(self._edge_active(steps, e.source, e.source_handle) for e in incoming):
                ready.append(node)
        return ready

    async def _skip_unreachable(
        self, session: AsyncSession, run: Run, graph: Graph, steps: dict[str, StepRun]
    ) -> bool:
        """Skip nodes whose parents are all resolved but none of whose edges were taken."""
        skipped_any = False
        changed = True
        while changed:
            changed = False
            for node in graph.nodes.values():
                incoming = graph.incoming(node.id)
                if node.id in steps or not incoming:
                    continue
                parents = [steps.get(e.source) for e in incoming]
                resolved = all(
                    p is not None and p.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
                    for p in parents
                )
                if resolved and not any(
                    self._edge_active(steps, e.source, e.source_handle) for e in incoming
                ):
                    steps[node.id] = await self._save_step(
                        session,
                        run,
                        StepRun(
                            run_id=run.id,
                            workspace_id=run.workspace_id,
                            node_id=node.id,
                            node_type=node.type,
                            status=StepStatus.SKIPPED,
                        ),
                    )
                    changed = skipped_any = True
        return skipped_any

    @staticmethod
    async def _save_step(session: AsyncSession, run: Run, step: StepRun) -> StepRun:
        session.add(step)
        run.updated_at = _now()
        await session.commit()
        await publish_step(run, step)
        return step

    async def _finish(
        self, session: AsyncSession, run: Run, status: RunStatus, error: str | None
    ) -> None:
        run.status = status
        run.error = error
        run.finished_at = _now()
        await session.commit()
        await publish_run(run)
        RUNS_FINISHED_TOTAL.labels(status.value).inc()
        logger.info("run_finished", run_id=str(run.id), status=status, error=error)

    async def _schedule_wakeups(self, run: Run, waiting: list[StepRun]) -> None:
        for step in waiting:
            if step.resume_at is not None:
                await self.deps.queue.enqueue(
                    "execute_run", run_id=str(run.id), _defer_until=step.resume_at
                )

    # --- node execution ----------------------------------------------------------------------

    def _node_context(
        self,
        session: AsyncSession,
        run: Run,
        node: Node,
        config: dict[str, Any],
        workflow_name: str,
        parent_outputs: dict[str, Any],
    ) -> NodeContext:
        async def resolve_credential(credential_id: str, types: tuple[str, ...]) -> dict[str, Any]:
            try:
                key = uuid.UUID(str(credential_id))
            except ValueError as exc:
                raise NodeExecutionError("Choose a credential", retryable=False) from exc
            credential = await session.scalar(
                select(Credential).where(
                    Credential.id == key, Credential.workspace_id == run.workspace_id
                )
            )
            if credential is None:
                raise NodeExecutionError(
                    "The selected credential no longer exists", retryable=False
                )
            if credential.type not in types:
                raise NodeExecutionError(
                    f"Credential '{credential.name}' has type {credential.type}; "
                    f"expected {' or '.join(types)}",
                    retryable=False,
                )
            try:
                return decrypt_json(credential.encrypted_data)
            except ServiceUnavailableError as exc:
                raise NodeExecutionError(exc.detail, retryable=False) from exc

        async def run_child(workflow_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
            return await self._run_child(run, workflow_id, payload)

        return NodeContext(
            node=node,
            config=config,
            run=run,
            workflow_name=workflow_name,
            session=session,
            llm=self.deps.llm,
            http=self.deps.http,
            queue=self.deps.queue,
            resolve_credential=resolve_credential,
            run_child=run_child,
            parent_outputs=parent_outputs,
        )

    async def _run_step(
        self,
        run_ref: Run,
        node: Node,
        graph: Graph,
        workflow_name: str,
        context: dict[str, Any],
        steps: dict[str, StepRun],
    ) -> None:
        """Run one node with retries and timeout in its own session (steps run concurrently)."""
        node_type = registry.get(node.type)
        async with self.deps.session_factory() as session:
            run = await session.get(Run, run_ref.id)
            if run is None:
                return
            started = time.perf_counter()
            step = StepRun(
                run_id=run.id,
                workspace_id=run.workspace_id,
                node_id=node.id,
                node_type=node.type,
                status=StepStatus.RUNNING,
                started_at=_now(),
            )
            await self._save_step(session, run, step)

            parent_outputs = {
                edge.source: steps[edge.source].output
                for edge in graph.incoming(node.id)
                if edge.source in steps and steps[edge.source].status == StepStatus.SUCCEEDED
            }
            result: NodeResult | None = None
            error: str | None = None
            try:
                if node_type is None:
                    raise NodeExecutionError(f"Unknown node type '{node.type}'", retryable=False)
                try:
                    config = render_value(node.config, context)
                except ExpressionError as exc:
                    raise NodeExecutionError(str(exc), retryable=False) from exc
                step.input = _json_safe(config)
                ctx = self._node_context(session, run, node, config, workflow_name, parent_outputs)
                result = await self._attempts(session, run, step, node, node_type.execute, ctx)
                for kind, usage in ctx.usage:
                    record_llm_usage(session, run.workspace_id, kind, usage)
            except NodeExecutionError as exc:
                error = str(exc)

            step.duration_ms = int((time.perf_counter() - started) * 1000)
            step.finished_at = _now()
            if error is not None:
                if node.settings.continue_on_error:
                    step.status, step.output = StepStatus.SUCCEEDED, {"error": error}
                    step.branch = None
                    step.error = error
                else:
                    step.status, step.error = StepStatus.FAILED, error
            elif result is not None and result.wait is not None:
                step.status = StepStatus.WAITING
                step.output = _json_safe(result.wait.output)
                step.resume_at = result.wait.resume_at
            elif result is not None:
                step.status = StepStatus.SUCCEEDED
                step.output = _json_safe(result.output)
                step.branch = result.branch
            await self._save_step(session, run, step)
            STEP_DURATION.labels(node.type, step.status.value).observe(step.duration_ms / 1000)
            if step.status == StepStatus.FAILED:
                raise StepFailedError(f"Step “{node.label}” failed: {error}")

    async def _attempts(
        self,
        session: AsyncSession,
        run: Run,
        step: StepRun,
        node: Node,
        action: Any,
        ctx: NodeContext,
    ) -> NodeResult:
        settings = node.settings
        attempt = 0
        while True:
            attempt += 1
            step.attempt = attempt
            try:
                result: NodeResult = await asyncio.wait_for(action(ctx), settings.timeout_seconds)
                return result
            except TimeoutError:
                error = NodeExecutionError(f"Timed out after {settings.timeout_seconds:g}s")
            except NodeExecutionError as exc:
                error = exc
            except ServiceUnavailableError as exc:
                error = NodeExecutionError(exc.detail)
            except httpx.HTTPError as exc:
                error = NodeExecutionError(f"Network error: {exc}")
            if not error.retryable or attempt > settings.retries:
                raise error
            await session.refresh(run, ["cancel_requested"])
            if run.cancel_requested:
                raise NodeExecutionError("Run was cancelled", retryable=False)
            delay = settings.retry_delay_seconds * 2 ** (attempt - 1)
            logger.info(
                "step_retry", run_id=str(run.id), node_id=node.id, attempt=attempt, delay=delay
            )
            await asyncio.sleep(delay)

    async def _resume_waiting(
        self,
        session: AsyncSession,
        run: Run,
        graph: Graph,
        workflow_name: str,
        steps: dict[str, StepRun],
    ) -> bool:
        progressed = False
        for step in [s for s in steps.values() if s.status == StepStatus.WAITING]:
            node = graph.nodes.get(step.node_id)
            node_type = registry.get(step.node_type)
            if node is None or node_type is None:
                continue
            ctx = self._node_context(session, run, node, step.input or {}, workflow_name, {})
            result = await node_type.resume(ctx, step)
            if result is None:
                continue
            step.status = StepStatus.SUCCEEDED
            step.output = _json_safe(result.output)
            step.branch = result.branch
            step.finished_at = _now()
            step.resume_at = None
            await self._save_step(session, run, step)
            progressed = True
        return progressed

    # --- child runs (sub-workflow, for-each) -------------------------------------------------

    async def _run_child(
        self, parent: Run, workflow_id: uuid.UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if parent.depth + 1 > MAX_CHILD_DEPTH:
            raise NodeExecutionError(
                f"Workflows can be nested at most {MAX_CHILD_DEPTH} levels deep", retryable=False
            )
        async with self.deps.session_factory() as session:
            workflow = await session.scalar(
                select(Workflow).where(
                    Workflow.id == workflow_id, Workflow.workspace_id == parent.workspace_id
                )
            )
            if workflow is None or workflow.published_version_id is None:
                raise NodeExecutionError(
                    "The workflow to run does not exist or is not published", retryable=False
                )
            version = await session.get(WorkflowVersion, workflow.published_version_id)
            if version is None:
                raise NodeExecutionError("The published version is missing", retryable=False)
            child = Run(
                workspace_id=parent.workspace_id,
                workflow_id=workflow.id,
                version_id=version.id,
                graph=version.graph,
                status=RunStatus.QUEUED,
                trigger_type=TriggerType.SUB_WORKFLOW,
                trigger_payload=_json_safe(payload),
                parent_run_id=parent.id,
                depth=parent.depth + 1,
            )
            session.add(child)
            await session.commit()
            child_id = child.id

        outcome = await self.execute(child_id, inline=True)
        async with self.deps.session_factory() as session:
            finished = await session.get(Run, child_id)
            if finished is None:
                raise NodeExecutionError("Child run disappeared")
            if outcome == Outcome.WAITING:
                await self._finish(
                    session,
                    finished,
                    RunStatus.FAILED,
                    "Workflows run from another workflow cannot pause (approval or delay)",
                )
            if finished.status != RunStatus.SUCCEEDED:
                raise NodeExecutionError(
                    f"Workflow “{workflow.name}” failed: {finished.error or finished.status}",
                    retryable=False,
                )
            graph = Graph.parse(finished.graph)
            rows = await session.scalars(
                select(StepRun).where(
                    StepRun.run_id == finished.id,
                    StepRun.status == StepStatus.SUCCEEDED,
                    StepRun.node_id.in_([n.id for n in graph.terminal_nodes()]),
                )
            )
            return {step.node_id: step.output for step in rows}
