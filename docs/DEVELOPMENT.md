# FlowForge — Development guide

## Setup

| Tool | Version | Used for |
|---|---|---|
| Docker Desktop | recent | Postgres, Redis, Mailpit (and optionally everything) |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python 3.12 + backend dependencies |
| Node.js | ≥ 22 | Frontend |

```bash
cp backend/.env.example backend/.env    # set CREDENTIALS_KEY (make credentials-key) and LLM_PROVIDER
make infra install migrate seed
make api      # terminal 1
make worker   # terminal 2 (on Windows, run the worker in Docker: docker compose up -d worker)
make web      # terminal 3
```

`backend/.env` is read automatically; every variable is documented in `backend/.env.example` and validated by `app/config.py` at startup. To let HTTP steps call services on your own machine, set `ALLOW_PRIVATE_NETWORK_REQUESTS=true` locally (never in production).

## Conventions

### Python (backend)

- PEP 8 via **ruff** (lint + format, line length 100). Imports sorted by ruff.
- **Type hints everywhere**; `mypy --strict` must pass for `app` and `tests`.
- Naming: modules/functions/variables `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- Layering:
  - `api/v1/*`: parse input, check permissions through dependencies (`ViewerAccess`, `MemberAccess`, `MemberOrKeyAccess`, …), call a service, return a schema. No business logic.
  - `services/*`: business rules. Take an `AsyncSession` explicitly. Raise `AppError` subclasses, never `HTTPException`.
  - `engine/*`: everything about executing a graph. It does not import from `api/` and only uses services for side effects such as email.
  - `models/*`: SQLAlchemy models only. `schemas/*`: Pydantic models only.
- Every query on tenant data filters by `workspace_id`, including lookups by primary key.
- Anything slow or failure-prone (runs, emails) goes to the worker through `JobQueue`.
- Comments explain *why*, not *what*.

### TypeScript (frontend)

- ESLint (Next.js config) + Prettier (with Tailwind class sorting), TypeScript `strict`.
- Components `PascalCase.tsx`; other modules `kebab-case.ts`; hooks start with `use`.
- Server state lives in TanStack Query; keys come from `src/lib/query-keys.ts` so real-time events can invalidate them.
- All API calls go through `src/lib/api-client.ts` (token refresh and Problem Details parsing in one place).
- The editor keeps React Flow nodes in its own history reducer (`features/editor/use-graph-history.ts`); `graph.ts` converts between the stored graph and React Flow's shape.

### REST & database

- Plural nouns, `kebab-case` paths, correct status codes (`201` create, `202` queued work, `204` no content).
- Tables plural `snake_case`; foreign keys `<entity>_id`; constraint names come from the naming convention in `app/db/base.py`.

### Commits

[Conventional Commits](https://www.conventionalcommits.org): `feat(engine): resume runs from the failed step`, `fix(webhooks): handle concurrent idempotent deliveries`, `docs: …`, `test: …`.

## Testing

```bash
cd backend && uv run pytest             # ~3 minutes; needs `make infra`
cd frontend && npm test                  # Vitest: graph conversion, undo/redo, API client
cd frontend && npx playwright test       # E2E against http://localhost:3000
```

- Backend tests use a separate database (`flowforge_test`, created by `infra/postgres/init.sql`) and Redis DB 15; tables are truncated after each test.
- The LLM is replaced by `FakeLLMClient`, which recognises the `Task:` line of each prompt and answers deterministically (classify picks a label mentioned in the text, extract reads `field: value` pairs, the agent calls the first tool once). `tests/unit/test_openrouter_client.py` checks the real client against mocked HTTP responses.
- Engine tests (`tests/integration/test_executor.py`) build graphs with the helpers in `tests/graphs.py` and run them inline with `RunExecutor.execute`. Outbound HTTP is mocked with `respx`.
- Jobs are captured with `InMemoryJobQueue`, so tests assert what would be enqueued (emails, deferred wake-ups).
- E2E tests expect the stack to run with `LLM_PROVIDER=fake` and a `CREDENTIALS_KEY`; they read emails from Mailpit (`E2E_MAILPIT_URL`, default `http://localhost:8025`).

## Database migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "add x to y"   # review the generated file!
uv run alembic upgrade head
uv run alembic check                                       # models and migrations agree
```

CI runs `upgrade → check → downgrade` on an empty database. Note: `workflows.published_version_id` and `workflow_versions.workflow_id` reference each other, so that foreign key is created after both tables (`use_alter`) — autogenerate does not emit it inside `create_table`.

## Adding a node type

Nodes are plugins: the engine never mentions a concrete node type ([ADR-0003](adr/0003-node-plugin-registry.md)).

1. Write a class in the matching module of `app/engine/nodes/` (`ai.py`, `logic.py`, `data.py`, `integrations.py`):

   ```python
   class UppercaseNode(NodeType):
       type = "uppercase"
       label = "Uppercase"
       description = "Upper-case a piece of text."
       category: ClassVar[NodeCategory] = NodeCategory.DATA
       icon = "type"
       config_schema: ClassVar[dict[str, Any]] = {
           "type": "object",
           "properties": {"text": {"type": "string", "title": "Text", "minLength": 1}},
           "required": ["text"],
       }

       async def execute(self, ctx: NodeContext) -> NodeResult:
           return NodeResult(output={"text": ctx.config["text"].upper()})
   ```

   - `ctx.config` is already rendered: `{{ … }}` expressions have been evaluated.
   - Raise `NodeExecutionError(message, retryable=False)` for errors a retry cannot fix (bad input); plain `NodeExecutionError` is retried according to the step settings.
   - Branching nodes return `NodeResult(branch=…)` and declare `static_handles` or `dynamic_handles_key`.
   - Use `ctx.http` through `engine/net.py::safe_request` for outbound calls (SSRF protection), `ctx.resolve_credential` for secrets, and `ctx.llm` for AI.
   - Pausing nodes set `pausable = True`, return `NodeResult(wait=Wait(...))` and implement `resume`.
2. Add an instance to `registry` in `app/engine/nodes/registry.py`.
3. If the icon name is new, map it in `frontend/src/features/editor/NodeIcon.tsx`.
4. Write tests in `tests/integration/test_executor.py` (behaviour) and, for config rules, `tests/unit/test_graph_validation.py`.

The palette, config form (generated from `config_schema`, with `x-ui` hints such as `textarea`, `json`, `tags`, `credential`, `workflow`) and validation pick the new node up automatically through `GET /node-types`.

## Other common extensions

| Task | Where |
|---|---|
| New credential type | `app/engine/credential_types.py` (fields are validated and encrypted automatically) |
| New AI prompt version | add `core/llm/prompts/<name>_v2.md`, switch the name in `engine/nodes/ai.py` |
| New template | JSON file in `app/templates/`; it must pass `validate_graph` (`test_every_template_is_valid` checks all of them) |
| New expression helper | filters/globals in `engine/expressions.py`; keep the sandbox tests green |
| New plan limit | `services/plans.py` |
| New real-time event | `engine/executor.py::publish_run/publish_step`, handled in `frontend/src/app/app/[workspaceId]/layout.tsx` |
| New background job | function in `workers/main.py`, add to `WorkerSettings.functions`, enqueue via `JobQueue` |
