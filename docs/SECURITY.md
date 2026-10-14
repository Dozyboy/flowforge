# FlowForge — Security

An automation platform runs user-defined logic that holds secrets and talks to the network, so most of its security work is about **what a workflow is allowed to do**, not only who may edit it.

## Access model

| Role | Can |
|---|---|
| `viewer` | Read workflows, versions, runs, approvals, credential names, dashboard |
| `member` | + create, edit, test-run, publish, activate and restore workflows; cancel and retry runs |
| `admin` | + credentials, members (except owners), invitations, API keys, rotate webhook secrets, delete workflows, audit log |
| `owner` | + manage owners, delete the workspace |
| API key | Read a workflow, start runs, list and read runs, in one workspace |
| Webhook sender | Start runs of one published, active workflow (per-workflow secret) |
| Approver | Decide one approval (token from the email link) |

Role checks happen in one dependency (`app/api/deps.py::require_workspace_role`). Requests for another workspace's resources return `404`, so IDs cannot be probed.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Code execution through workflows | No "run code" node ([ADR-0005](adr/0005-no-arbitrary-code-execution.md)). Expressions use Jinja2's `ImmutableSandboxedEnvironment`: no attribute access to internals (`__class__`, `mro`), no mutation, `StrictUndefined`, output size limits ([ADR-0004](adr/0004-sandboxed-jinja-expressions.md)); covered by sandbox-escape tests |
| SSRF from HTTP steps, Slack/Telegram/Sheets URLs | `engine/net.py`: only http(s); every hostname resolved and rejected if any address is private, loopback, link-local, multicast or reserved; redirects followed manually and re-checked at each hop; response size capped |
| Secrets leaking into run history | Credentials are referenced by ID in the graph and decrypted only inside the step; step input stores the rendered config, which contains the ID, never the secret. Webhook secret, cookie and authorization headers are removed from stored trigger payloads |
| Stolen database | Credentials encrypted with Fernet (AES-128-CBC + HMAC) using `CREDENTIALS_KEY` from the environment ([ADR-0006](adr/0006-encrypted-credential-vault.md)); webhook secrets, API keys, refresh tokens, approval, email and invitation tokens stored as SHA-256 hashes only |
| Forged or replayed webhooks | Per-workflow secret compared in constant time; `Idempotency-Key` deduplicated by a unique constraint; secret rotation; per-IP rate limit |
| Approval link abuse | 256-bit random token, single decision, expiry; the page shows only the workflow name and the approval message |
| Resource exhaustion | Plan limits on workflows, monthly runs and concurrent runs; per-step timeout (max 300 s); run time budget; for-each item cap; sub-workflow depth limit (3); response and webhook body size caps |
| Stolen access token (e.g. XSS) | 15-minute JWT kept in memory only; refresh token in an `HttpOnly` cookie, rotated on every use, family revoked on reuse |
| Password guessing | bcrypt hashes (computed off the event loop); per-IP rate limit on auth endpoints; identical error and similar timing for unknown emails |
| Cross-tenant access | `workspace_id` filter on every query, including credential lookups inside the engine; dedicated tests |
| Clickjacking of the editor or approval page | `X-Frame-Options: DENY` on every page |
| Prompt injection through workflow data | AI steps only return text or JSON; the agent can call only the HTTP tools the builder configured on that step, through the same SSRF-safe client, with a step limit |
| Tokens in URLs/logs | WebSockets use one-time tickets (30 s TTL) instead of access tokens |
| Missing audit trail | Workflow publish, activation/pause, restore and deletion, secret rotation, credential, API key and member changes are written to `audit_logs` in the same transaction |

## Secrets

- All secrets come from environment variables; `.env` files are git-ignored and `.env.example` contains placeholders only.
- Losing `CREDENTIALS_KEY` makes stored credentials unreadable (users must re-enter them); leaking it together with the database exposes them. Store it separately from database backups.
- The pre-commit configuration includes `detect-private-key`.

## Reporting a vulnerability

Please do not open a public issue. Email the maintainers with steps to reproduce; we aim to respond within 72 hours.
