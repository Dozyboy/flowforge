# FlowForge — Product & Design

## 1. Problem

Small teams repeat the same multi-step chores every day: read an incoming form, decide who should handle it, write a reply or summary, post to Slack, add a row to a spreadsheet, wait for a manager to approve. Writing a custom script for each is slow and fragile; generic automation tools struggle with the "judgement" steps (is this a refund request or a bug report?) that large language models are now good at.

## 2. Solution

FlowForge is a multi-tenant workflow automation platform with AI steps built in:

- A **visual editor** to connect triggers, AI steps, logic and integrations.
- A **reliable execution engine** that runs branches in parallel, retries failing steps, pauses for human approval or delays, and can resume a failed run from the step that failed.
- **Full observability**: every run and every step is recorded with input, output, error and duration, and can be watched live.

## 3. Personas

| Persona | Goal |
|---|---|
| **Builder** (ops lead, founder) | Build and publish workflows without code, test them with sample data |
| **Approver** (manager, often without an account) | Approve or reject a step from an email link |
| **Operator** (on-call teammate) | See failed runs, understand why, retry or resume |
| **Developer** | Trigger workflows from their own systems via webhooks or the API |

## 4. User stories

Building
- As a builder, I drag nodes onto a canvas, connect them, and configure each node in a form generated from its schema.
- As a builder, I see validation problems (missing trigger, cycles, empty required fields) before publishing.
- As a builder, I use `{{ trigger.body.email }}` or `{{ steps.classify.output.label }}` to pass data between steps.
- As a builder, I start from a template and export/import workflows as JSON.
- As a builder, I test-run my draft and watch each node light up as it executes.
- As a builder, I publish a version; triggers always run the published version, and I can roll back.

Running
- As a developer, I call a webhook URL with a secret; repeated deliveries with the same idempotency key start only one run.
- As a builder, I schedule a workflow with a cron expression in my time zone.
- As an approver, I receive an email and approve or reject in one click; the run continues on the matching branch.
- As an operator, I see failed runs, the failing step and its error, and resume the run from that step after fixing the cause.
- As an operator, I cancel a run that is stuck or wrong.

Workspace
- As an admin, I store API keys and tokens for integrations once, encrypted, and reference them from nodes by name.
- As an owner, I see run volume, success rate and AI cost, and stay within my plan's limits.

## 5. Scope

### In scope (v1)
- Workspaces, roles (`owner`, `admin`, `member`, `viewer`), invitations, API keys, audit log (shared platform).
- Editor: palette, schema-driven config forms, validation, undo/redo, keyboard shortcuts, live run overlay.
- Node types: 3 triggers, 5 AI nodes (including a tool-using agent), 8 logic/data nodes, 6 integrations.
- Engine: DAG execution, parallel branches, conditional and multi-way routing, merge, for-each over a sub-workflow, delays, human approval, retries with exponential backoff, per-step timeout, continue-on-error, cancellation, resume from failed step, concurrency limit per workspace, recovery of runs interrupted by worker crashes.
- Versioning with diff and rollback; templates; JSON import/export.
- Encrypted credential vault.
- Run history, live updates, dashboard metrics, plan limits, LLM cost tracking.

### Out of scope (v1)
- Arbitrary code nodes (see [ADR-0005](adr/0005-no-arbitrary-code-execution.md)).
- Email-inbound triggers, OAuth app connections (credentials are pasted tokens).
- Loops with arbitrary back-edges (iteration is expressed as for-each over a sub-workflow).
- Payment processing. Plans and their limits are enforced; collecting money is out of scope.

## 6. Product rules

| Rule | Value |
|---|---|
| A workflow must have exactly one trigger node and no cycles | validated on save and publish |
| Triggers (webhook, schedule) run the **published** version | drafts only run through "Test run" |
| Default step timeout / max | 30 s / 300 s |
| Retries per step | 0–5, exponential backoff starting at the configured delay |
| For-each | at most 100 items, up to 10 in parallel |
| Approval links | expire after the configured hours (default 72) |
| Free plan | 5 workflows, 1,000 runs / month, 2 concurrent runs, 2 members |
| Pro plan | 100 workflows, 50,000 runs / month, 10 concurrent runs, 20 members |

## 7. Key decisions

| Decision | Choice | Why | ADR |
|---|---|---|---|
| Workflow model | Directed acyclic graph stored as JSON (React Flow format) | Easy to render, diff and version; validation is a graph problem | [0001](adr/0001-workflows-as-json-dag.md) |
| Execution | Own engine in the worker; state persisted per step | Pause/resume, retries and live progress need step-level state | [0002](adr/0002-step-level-persisted-execution.md) |
| Node architecture | Plugin registry; each node declares a JSON Schema | New nodes need no engine or UI changes | [0003](adr/0003-node-plugin-registry.md) |
| Expressions | Jinja2 sandboxed environment | Familiar syntax, safe evaluation of user input | [0004](adr/0004-sandboxed-jinja-expressions.md) |
| Custom code | Not supported | Running tenant code safely needs real isolation | [0005](adr/0005-no-arbitrary-code-execution.md) |
| Secrets | Fernet-encrypted credential vault, write-only API | Tokens never reach the browser or logs | [0006](adr/0006-encrypted-credential-vault.md) |
| Scheduling | Per-minute scheduler job using `next_run_at` + `SKIP LOCKED` row locks | Works with many workers, survives restarts | [0007](adr/0007-scheduling-with-next-run-at.md) |

## 8. Success metrics

- Run success rate per workflow; time to detect and resume a failed run.
- Median and p95 run duration.
- AI cost per run.
