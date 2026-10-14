# FlowForge — API

The full, always-current reference is generated from the code: run the API and open **`/docs`** (Swagger UI) or **`/openapi.json`**. This page explains the conventions and the most important flows.

## Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1` |
| Format | JSON, `snake_case` fields, ISO 8601 timestamps in UTC |
| Tenancy | Workspace resources live under `/api/v1/workspaces/{workspace_id}/…` |
| Pagination | `limit` / `offset` query parameters. Runs return `{ items, total, limit, offset }`; the audit log returns a plain array |
| Errors | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) `application/problem+json` (see below) |
| Request IDs | Send `X-Request-ID` or receive a generated one; it appears in every log line |

### Error format

```json
{
  "type": "https://errors.flowforge.dev/workflow_invalid",
  "title": "Bad Request",
  "status": 400,
  "detail": "The workflow has problems that must be fixed before publishing",
  "code": "workflow_invalid",
  "instance": "/api/v1/workspaces/…/workflows/…/publish",
  "issues": [{ "node_id": "classify", "message": "'text' is a required property" }]
}
```

| Status | `code` | Meaning |
|---|---|---|
| 400 | `bad_request`, `workflow_invalid` | Invalid operation; `workflow_invalid` carries `issues` per node |
| 401 | `unauthenticated` | Missing or invalid credentials, wrong webhook secret |
| 402 | `quota_exceeded` | Plan limit reached (workflows, monthly runs, members) |
| 403 | `permission_denied` | Authenticated but role too low |
| 404 | `not_found` | Missing, or belongs to another workspace |
| 409 | `conflict` | Duplicate or state conflict (e.g. retrying a run that is still running) |
| 422 | `validation_error` | Request body or query failed validation |
| 429 | `rate_limited` | Includes `retry_after` seconds |
| 503 | `service_unavailable` | AI provider or credential vault not configured |

## Authentication

| Client | How |
|---|---|
| App user | `Authorization: Bearer <access_token>` (15 min). Refresh via `POST /auth/refresh` with the `ff_refresh` httpOnly cookie |
| Integration | `Authorization: Bearer ff_…` API key, scoped to one workspace: read a workflow, start runs, list and read runs |
| Webhook sender | `X-FlowForge-Secret: <secret>` header (or `?secret=`), per workflow |
| Approver | The signed token in the approval link; no account needed |

## Endpoints

### Auth — `/auth`
| Method | Path | Description |
|---|---|---|
| POST | `/register` | Create account, sign in, send verification email |
| POST | `/login` | Sign in |
| POST | `/refresh` | Rotate refresh token, get a new access token |
| POST | `/logout`, `/logout-all` | End this session / all sessions |
| POST | `/verify-email`, `/resend-verification` | Email verification |
| POST | `/forgot-password`, `/reset-password` | Password reset |
| GET/PATCH | `/me` | Current user and workspaces / update profile |
| POST | `/me/password` | Change password (signs out other sessions) |

### Workspaces & team
| Method | Path | Role |
|---|---|---|
| GET/POST | `/workspaces` | any user |
| GET/PATCH/DELETE | `/workspaces/{id}` | viewer / admin / owner |
| GET | `/workspaces/{id}/usage` | viewer: plan limits, runs this month, AI tokens and cost |
| GET | `/workspaces/{id}/dashboard?days=14` | viewer: run counts per day, success rate, failing workflows |
| GET | `/workspaces/{id}/approvals` | viewer: approvals waiting for a decision |
| GET | `/workspaces/{id}/audit-logs` | admin |
| GET/PATCH/DELETE | `/workspaces/{id}/members[/{membership_id}]` | viewer / admin / admin |
| GET/POST/DELETE | `/workspaces/{id}/invitations[/{invitation_id}]` | admin |
| POST | `/invitations/accept` | invited user |
| GET/POST/DELETE | `/workspaces/{id}/api-keys[/{api_key_id}]` | admin |

### Workflows — `/workspaces/{id}/workflows`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/` | viewer | List with trigger, state, last run, runs in the last 7 days |
| POST | `/` | member | Create (optionally `template_id`) |
| POST | `/import` | member | Import an exported `flowforge.workflow/v1` document |
| GET | `/{workflow_id}` | viewer, API key | Draft graph, validation `issues`, webhook URL |
| PATCH | `/{workflow_id}` | member | Save name/description/draft graph; returns `issues` (saving never fails on them) |
| DELETE | `/{workflow_id}` | admin | Delete the workflow |
| POST | `/{workflow_id}/publish` | member | Validate and create a new version; returns the webhook secret **once** on first publish |
| POST | `/{workflow_id}/activation` | member | `{ "active": false }` pauses webhook and schedule triggers |
| POST | `/{workflow_id}/webhook-secret` | admin | Rotate the secret (old one stops working) |
| GET | `/{workflow_id}/export` | viewer | Portable JSON (no credentials) |
| POST | `/{workflow_id}/runs` | member, API key | `{ "payload": {…}, "use_draft": true }`; `202` with the queued run |
| GET | `/{workflow_id}/versions[/{version}]` | viewer | Version history / one version's graph |
| GET | `/{workflow_id}/versions/{version}/diff` | viewer | Added, removed and changed nodes and edges vs. the draft |
| POST | `/{workflow_id}/versions/{version}/restore` | member | Copy a version into the draft |

### Runs — `/workspaces/{id}/runs`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/?workflow_id=&status=` | viewer, API key | Paginated, newest first |
| GET | `/{run_id}` | viewer, API key | Graph snapshot, every step (input, output, branch, error, duration), child runs |
| POST | `/{run_id}/cancel` | member | Cooperative cancel: running steps finish, nothing new starts |
| POST | `/{run_id}/retry` | member | `{ "from_failed_step": true }` reuses outputs of steps that succeeded |

### Credentials — `/workspaces/{id}/credentials`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/` | viewer | Names and types only; secret values are never returned |
| POST | `/` | admin | `{ "name", "type", "data": {…} }`, validated against the credential type |
| PATCH/DELETE | `/{credential_id}` | admin | Rename, replace secrets, delete |

### Catalog (any signed-in user)
| Method | Path | Description |
|---|---|---|
| GET | `/node-types` | Every node type: category, JSON Schema for its config, output handles |
| GET | `/credential-types` | Credential types and their fields |
| GET | `/templates` | Workflow gallery |
| GET | `/plans` | Plan limits |

### Public
| Method | Path | Description |
|---|---|---|
| POST | `/hooks/{workflow_id}` | Start a run of the published version (see below) |
| GET | `/approvals/{token}` | Approval details for the approver page |
| POST | `/approvals/{token}` | `{ "decision": "approve" \| "reject", "name", "comment" }` |

### Real-time
| Method | Path | Description |
|---|---|---|
| POST | `/ws-tickets` | One-time ticket (30 s) for `{ "workspace_id" }` |
| WS | `/ws?ticket=…` | Events: `run.updated` (status changes, including waiting for approval) and `step.updated` |

### Operations
| Path | Description |
|---|---|
| `GET /health` | Liveness |
| `GET /ready` | Readiness (database and Redis reachable) |
| `GET /metrics` | Prometheus metrics of the API process (the worker serves its own on `WORKER_METRICS_PORT`) |

## Webhooks in detail

```bash
curl -X POST https://api.example.com/api/v1/hooks/3f6c…e1 \
  -H "Content-Type: application/json" \
  -H "X-FlowForge-Secret: whsec_…" \
  -H "Idempotency-Key: ticket-8812" \
  -d '{"email": "sam@example.com", "message": "Please refund my order"}'
```

```json
HTTP/1.1 202 Accepted
{ "run_id": "9b1d…", "status": "queued", "duplicate": false }
```

- The body may be JSON, form data or plain text (max 1 MB). Inside the workflow it is available as `{{ trigger.body }}`, with `{{ trigger.query }}` and `{{ trigger.headers }}` (the secret, cookies and authorization headers are removed).
- Repeating a request with an `Idempotency-Key` already seen for this workflow returns `200` with `"duplicate": true` and the original `run_id`; no second run starts. A unique constraint makes this hold even for concurrent deliveries.
- The workflow must be published and active; otherwise `404`. A wrong secret returns `401`.
- Rate limit: 120 requests per minute per workflow and sender IP.

## Approvals in detail

An `approval` step creates an approval with a random token (only its SHA-256 hash is stored), emails each approver a link to `/approvals/{token}` and puts the run in `waiting`. The worker is free while the run waits. `POST /approvals/{token}` records the decision, the approver's name and comment, and enqueues the run, which continues on the `approved` or `rejected` branch. A housekeeping job expires overdue approvals; their runs continue on the `rejected` branch with `"status": "expired"` in the step output.
