.DEFAULT_GOAL := help
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

API := apps/api

# Use a global pnpm when there is one, otherwise the exact version pinned in package.json.
PNPM ?= $(shell command -v pnpm >/dev/null 2>&1 && echo pnpm || echo npx -y $$(node -p "require('./package.json').packageManager"))

.PHONY: help install hooks lint format typecheck architecture test check api

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

typecheck: ## Run mypy in strict mode
	cd $(API) && uv run mypy

architecture: ## Check module and layer boundaries (import-linter)
	cd $(API) && uv run lint-imports

test: ## Run the unit tests with coverage
	cd $(API) && uv run pytest --cov

check: lint typecheck architecture test ## Everything CI runs, locally

api: ## Run the API with hot reload on http://localhost:8000
	cd $(API) && uv run uvicorn wiredex.bootstrap.app:create_app --factory --reload --port 8000
