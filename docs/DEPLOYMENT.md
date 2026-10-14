# FlowForge — Deployment

FlowForge is three processes plus two managed services:

| Process | Image | Scales |
|---|---|---|
| `api` | `backend/Dockerfile` (uvicorn) | horizontally (stateless; realtime uses Redis pub/sub) |
| `worker` | same image, `arq app.workers.main.WorkerSettings` | horizontally: run locks and `SKIP LOCKED` scheduling make several workers safe |
| `web` | `frontend/Dockerfile` (Next.js standalone) | horizontally |
| PostgreSQL 16 | managed (Neon, Supabase, RDS, Cloud SQL) or container | vertically |
| Redis 7 | managed (Upstash, ElastiCache) or container | — |

The worker runs the scheduler cron (every minute) and housekeeping (expired approvals, stuck runs) as well as runs and emails. Every worker may run the cron safely: schedule slots are claimed with `FOR UPDATE SKIP LOCKED` ([ADR-0007](adr/0007-scheduling-with-next-run-at.md)).

## Option A — single VPS with Docker Compose

Good for demos and small teams (2 vCPU / 4 GB RAM is enough).

1. Install Docker and clone the repository.
2. Create `backend/.env` from `.env.example` with production values (see the checklist below).
3. Put a reverse proxy with TLS in front (Caddy is the simplest):

   ```caddy
   app.example.com {
     reverse_proxy web:3000
   }
   api.example.com {
     reverse_proxy api:8000
   }
   ```

4. Build the frontend with public URLs, then start:

   ```bash
   docker compose build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com web
   docker compose up -d --wait
   ```

5. Back up the Postgres volume daily (`pg_dump`) **and keep `CREDENTIALS_KEY` in a password manager**: a database backup without the key cannot decrypt credentials.

Remove the Mailpit service and point `SMTP_*` at a real provider (Postmark, SES, Resend, Mailgun); approval emails depend on it.

## Option B — managed platforms

| Part | Example |
|---|---|
| Frontend | Vercel: root `frontend`, env `API_INTERNAL_URL=https://api.example.com`, `NEXT_PUBLIC_API_URL=https://api.example.com` |
| API + worker | Render / Railway / Fly.io: two services from `backend/Dockerfile`; worker start command `arq app.workers.main.WorkerSettings`; API pre-deploy command `alembic upgrade head` |
| Database | Neon, Supabase or the platform's Postgres |
| Redis | Upstash or the platform's Redis |

Webhook senders call the **API** domain (`https://api.example.com/api/v1/hooks/{id}`); set `PUBLIC_API_URL` so the editor shows the right URL.

## Production checklist

| Setting | Value |
|---|---|
| `ENVIRONMENT` | `production` (JSON logs) |
| `JWT_SECRET` | 48+ random bytes, never reused |
| `CREDENTIALS_KEY` | Fernet key, stored outside the server as well; rotating it requires re-encrypting credentials |
| `COOKIE_SECURE` | `true` (HTTPS only) |
| `PUBLIC_APP_URL`, `PUBLIC_API_URL` | real HTTPS URLs (used in approval emails and webhook URLs) |
| `DATABASE_URL`, `REDIS_URL` | managed services with TLS |
| `ALLOW_PRIVATE_NETWORK_REQUESTS` | `false` (the default): HTTP steps must not reach your internal network |
| `OPENROUTER_API_KEY` | production key with a spending limit set on OpenRouter |
| `OPENROUTER_FALLBACK_MODELS` | at least one fallback model |
| `SMTP_*`, `EMAIL_FROM` | real provider, verified sending domain (SPF/DKIM) |
| `RUN_JOB_TIMEOUT_SECONDS` | upper bound for one execution slice of a run (waiting time does not count) |

Also:

- Run `alembic upgrade head` before starting new API versions.
- Scrape `/metrics` on the API and port `WORKER_METRICS_PORT` (default 9100) on each worker. Alert on 5xx rate, `workflow_runs_finished_total{status="failed"}`, p95 of `workflow_step_duration_seconds` and `llm_requests_total{outcome="error"}`.
- Use `/ready` for load balancer health checks and `/health` for liveness.
- Ship logs to a log platform; filter by `request_id` (API) or `run_id` (engine) to follow one request or run.
- Size worker concurrency (`max_jobs`, default 20) to your outbound rate limits; plan limits cap concurrent runs per workspace.
