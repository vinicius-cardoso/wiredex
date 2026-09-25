.DEFAULT_GOAL := help
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

API := apps/api

# Use a global pnpm when there is one, otherwise the exact version pinned in package.json.
PNPM ?= $(shell command -v pnpm >/dev/null 2>&1 && echo pnpm || echo npx -y $$(node -p "require('./package.json').packageManager"))

.PHONY: help install hooks lint format typecheck architecture test test-integration e2e check api web client db db-down psql restore-drill coverage migrate migration

help: ## List the available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and Node dependencies
	cd $(API) && uv sync
	$(PNPM) install

hooks: ## Install the git pre-commit and commit-msg hooks
	uvx pre-commit install

lint: ## Lint and check formatting without changing files
	cd $(API) && uv run ruff check . && uv run ruff format --check .
	$(PNPM) exec biome ci .

format: ## Fix lint issues and format everything
	cd $(API) && uv run ruff check --fix . && uv run ruff format .
	$(PNPM) exec biome check --write .

typecheck: ## mypy strict for the API, tsc for every TypeScript package
	cd $(API) && uv run mypy
	$(PNPM) -r typecheck

architecture: ## Check module and layer boundaries (import-linter)
	cd $(API) && uv run lint-imports

test: ## Run the API and web unit tests (fast, no database)
	cd $(API) && uv run pytest
	$(PNPM) -r test

coverage: ## Run every API test, unit and integration, with the coverage floor (needs Docker)
	cd $(API) && uv run pytest -m "integration or not integration" --cov

test-integration: ## Run the API integration tests against a throwaway Postgres (needs Docker)
	cd $(API) && uv run pytest -m integration

e2e: db ## Run the Playwright end-to-end tests against the real API, database and web build
	$(PNPM) --filter @wiredex/e2e exec playwright install chromium
	$(PNPM) --filter @wiredex/e2e e2e

check: lint typecheck architecture test ## Everything CI runs, locally

api: ## Run the API with hot reload on http://localhost:9000 (reads .env if present)
	set -a; [ -f .env ] && . ./.env; set +a; cd $(API) && uv run uvicorn wiredex.bootstrap.app:create_app --factory --reload --port 9000

web: ## Run the web app with hot reload on http://localhost:5173 (proxies /api to :9000)
	$(PNPM) --filter @wiredex/web dev

client: ## Regenerate packages/api-client from the API's OpenAPI schema
	cd $(API) && uv run python -m wiredex.bootstrap.openapi > ../../packages/api-client/src/generated/openapi.json
	$(PNPM) --filter @wiredex/api-client generate

migrate: db ## Apply the database migrations to the local Postgres
	set -a; [ -f .env ] && . ./.env; set +a; cd $(API) && uv run wiredex db upgrade

migration: ## Autogenerate the next migration from the models: make migration m="add users"
	@test -n "$(m)" || { echo 'usage: make migration m="what it does"'; exit 1; }
	set -a; [ -f .env ] && . ./.env; set +a; cd $(API) && uv run wiredex db revision -m "$(m)"

db: ## Start Postgres in Docker and wait until it is healthy
	docker compose up -d --wait db

db-down: ## Stop Postgres (data is kept in the db-data volume)
	docker compose down

psql: ## Open a psql shell on the local database
	docker compose exec db psql -U $${POSTGRES_USER:-wiredex} -d $${POSTGRES_DB:-wiredex}

restore-drill: ## Restore the newest production backup into a throwaway Postgres (from this machine)
	bash deploy/restore-drill.sh
