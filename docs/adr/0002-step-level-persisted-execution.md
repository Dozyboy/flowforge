# ADR-0002: Own execution engine with step-level persisted state

- Status: Accepted

## Context

Runs must survive worker restarts, pause for hours (approvals, delays), resume on any worker, retry single steps, resume from a failed step, and stream progress to the UI. Options: a workflow engine product (Temporal, Prefect), a task-graph library (Celery canvas), or a small engine on top of the existing job queue.

## Decision

Write a focused engine (`app/engine/executor.py`) that runs inside an arq job. The source of truth is the database: one `step_runs` row per node per run, upserted after each step. Each invocation of `execute_run` reconstructs the state from those rows, finds the nodes that are ready, runs them, and stops when nothing is ready (finished, failed, or waiting).

## Consequences

- Pausing is just "stop the job"; resuming is "enqueue the job again". Any worker can continue any run.
- Resume-from-failure copies successful steps into a new run and calls the same loop.
- Every step is visible in the UI with input, output, error and duration.
- More database writes per run than an in-memory executor. Fine for the expected volume; batching writes is a known optimisation.
- Not a replacement for Temporal-class durability (e.g. exactly-once side effects). Steps with side effects should be idempotent or have `retries: 0`; this is documented in the node settings.
