# ADR-0007: Scheduling with a `next_run_at` column and a per-minute tick

- Status: Accepted

## Context

Workflows with a schedule trigger must start at their cron times, in the user's time zone, exactly once, even with several workers and across restarts. Options: an in-process scheduler (APScheduler) holding all jobs in memory, one arq cron entry per workflow (static at startup), or a database-driven tick.

## Decision

- On publish, compute `next_run_at` from the cron expression and time zone (`croniter` + `zoneinfo`) and store it on the workflow.
- A worker cron job runs every minute. It selects active workflows with `next_run_at <= now()` using `SELECT … FOR UPDATE SKIP LOCKED`, advances their `next_run_at` and commits (claiming the slots), then creates the runs. Concurrent workers skip rows another worker has locked, so each slot starts exactly one run.

## Consequences

- No in-memory state: restarts and new deployments do not lose schedules.
- Uses an index on `next_run_at`; cheap even with many workflows.
- Minute granularity, which matches cron.
- If the scheduler was down, each overdue workflow runs once on recovery (missed slots are not replayed), which is the safer default for automations with side effects.
