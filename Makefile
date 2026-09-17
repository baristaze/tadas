# Tadas developer entry points. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE ?= docker compose -f deployment/local/docker-compose.yml
COMPOSE_FULL := $(COMPOSE) -f deployment/local/docker-compose.full.yml
ROLES := core activity queue admin

.PHONY: help setup up down reset urls infra-up devx-up stack-up infra-down migrate seed migrate-check check lint format-check typecheck test-unit test-integration openapi

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install every Python and TypeScript dependency
	uv sync --all-packages
	@if [ -f pnpm-workspace.yaml ] && [ -d apps ]; then pnpm install; fi

# The one-command session. `up` starts the data services first, migrates and
# seeds them, then starts the app containers and the dashboards; it is safe
# to rerun and keeps data. `down` keeps data; `reset` wipes it and starts over.
up: .env ## Everything: stack, migrations, seed, app containers, dashboards; keeps data
	$(COMPOSE) up -d --wait
	$(MAKE) --no-print-directory migrate seed
	$(COMPOSE_FULL) --profile devx up -d --build --wait
	@$(MAKE) --no-print-directory urls

down: ## Stop every local container; the data stays for the next `make up`
	$(COMPOSE_FULL) --profile devx down --remove-orphans

reset: ## Wipe every container and all local data, then `make up`
	$(MAKE) --no-print-directory infra-down
	$(MAKE) --no-print-directory up

urls: ## Print the local URLs and the seeded sign-in
	@echo ""
	@echo "  Portal         http://localhost:55173   sign in: $(SEED_EMAIL) / $(SEED_PASSWORD)"
	@echo "  API docs       http://127.0.0.1:8000/docs"
	@echo "  pgweb          http://localhost:58081"
	@echo "  Valkey Admin   http://localhost:58080"
	@echo "  ElasticMQ UI   http://localhost:53000"
	@echo "  Grafana        http://localhost:53001   metrics dashboards, no sign-in"
	@echo "  Prometheus     http://localhost:59090"
	@echo "  Jaeger         http://localhost:56686"
	@echo "  GlitchTip      http://localhost:58000   admin@example.test / tadas-local"
	@echo "  MinIO console  http://localhost:59001   tadas / tadastadas"
	@echo ""

.env:
	cp .env.example .env

infra-up: ## Start Postgres, the cache, the queue, and the object store
	$(COMPOSE) up -d --wait

devx-up: ## The local stack plus developer dashboards (pgweb, Valkey Admin, ElasticMQ UI, Prometheus, Grafana, Jaeger, GlitchTip)
	$(COMPOSE) --profile devx up -d --wait

stack-up: ## The local stack plus the api, maintenance, and portal containers
	$(COMPOSE_FULL) up -d --build --wait

# Names every file and profile so no container of any of them is left behind.
infra-down: ## Stop every local container, dashboards and app containers too, and drop the volumes
	$(COMPOSE_FULL) --profile devx down -v --remove-orphans

migrate: ## Apply every role's migration chain to the local database
	uv run --package tadas-om python -m tadas.om.storage.migrate upgrade --all

# Local-only sign-in; override any of these on the command line, e.g.
# `make seed SEED_EMAIL=me@example.test`.
SEED_ORG ?= Acme
SEED_SLUG ?= acme
SEED_NAME ?= Local Owner
SEED_EMAIL ?= owner@example.test
SEED_PASSWORD ?= tadas-local

seed: ## Create a local org and its owner to sign in with; a no-op once it exists
	uv run --package tadas-api tadas-api bootstrap --if-absent \
		--org "$(SEED_ORG)" --slug "$(SEED_SLUG)" --name "$(SEED_NAME)" \
		--email "$(SEED_EMAIL)" --password "$(SEED_PASSWORD)"

# The ORM-versus-schema check needs a migrated database, which the fast gate
# cannot reach, so `check` does not run it; CI's integration job runs it
# right after `make migrate`, and the downgrade-then-upgrade round trip stays
# in the integration tests.
migrate-check: ## Compare every role's ORM metadata with the migrated schema
	uv run --package tadas-om python -m tadas.om.storage.migrate check --all

check: lint format-check typecheck test-unit ## The fast local gate
	@if [ -d apps ]; then pnpm run lint && pnpm run typecheck && pnpm run test; fi

lint: ## Ruff lint
	uv run ruff check .

format-check: ## Ruff format, check only
	uv run ruff format --check .

typecheck: ## Pyright over every distribution
	uv run pyright

test-unit: ## Unit tests over the memory impls
	uv run pytest -q -m "not integration and not e2e"

test-integration: ## Integration tests over the compose stack
	uv run pytest -q -m integration

openapi: ## Emit the API document into the apps that consume it and regenerate their types
	uv run --package tadas-api tadas-api openapi --out clients/api-client/openapi.json
	pnpm --filter @tadas/api-client generate
