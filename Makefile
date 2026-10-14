.DEFAULT_GOAL := help
COMPOSE := docker compose
BACKEND := cd backend &&
FRONTEND := cd frontend &&

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Run the whole stack in Docker (http://localhost:3000)
	$(COMPOSE) up -d --build --wait

down: ## Stop all containers
	$(COMPOSE) down

logs: ## Follow API and worker logs
	$(COMPOSE) logs -f api worker

infra: ## Start only Postgres, Redis and Mailpit (for local development)
	$(COMPOSE) up -d --wait postgres redis mailpit

install: ## Install backend and frontend dependencies
	$(BACKEND) uv sync
	$(FRONTEND) npm ci

migrate: ## Apply database migrations
	$(BACKEND) uv run alembic upgrade head

seed: ## Create the demo account, workflows and runs
	$(BACKEND) uv run python -m app.scripts.seed

seed-docker: ## Seed the database of the Docker stack
	$(COMPOSE) exec api python -m app.scripts.seed

api: ## Run the API with auto-reload
	$(BACKEND) uv run uvicorn app.main:app --reload --port 8000

worker: ## Run the background worker (runs, schedules, emails)
	$(BACKEND) uv run arq app.workers.main.WorkerSettings

web: ## Run the frontend dev server
	$(FRONTEND) npm run dev

credentials-key: ## Print a new CREDENTIALS_KEY for backend/.env
	$(BACKEND) uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

lint: ## Lint and type-check everything
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	$(FRONTEND) npm run lint && npm run typecheck && npm run format:check

test: ## Run backend and frontend unit/integration tests
	$(BACKEND) uv run pytest
	$(FRONTEND) npm test

e2e: ## Run Playwright end-to-end tests against a running stack
	$(FRONTEND) npx playwright test

.PHONY: help up down logs infra install migrate seed seed-docker api worker web credentials-key lint test e2e
