# Tadas developer entry points. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash

# The knobs live in one place: .env.example carries every default and .env
# (which `make up` copies from it) the developer's overrides. Make reads both
# so `make seed` and `make urls` say what the compose stack does, and compose
# reads the same two files for the dashboard ports.
include .env.example
ifneq ($(wildcard .env),)
include .env
endif
COMPOSE_ENV := --env-file .env.example $(if $(wildcard .env),--env-file .env)
COMPOSE ?= docker compose $(COMPOSE_ENV) -f deployment/local/docker-compose.yml
COMPOSE_FULL := $(COMPOSE) -f deployment/local/docker-compose.full.yml
ROLES := core activity queue admin

.PHONY: help setup up down reset urls infra-up devx-up stack-up infra-down migrate seed demo-gif demo-cli-gif migrate-check check lint format-check typecheck test-unit test-integration openapi

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
	@echo "  Portal         http://localhost:55173   sign in: $(SEED_EMAIL) or $(SEED_MEMBER_EMAIL) / $(SEED_PASSWORD)"
	@echo "  API docs       http://127.0.0.1:8000/docs"
	@echo "  pgweb          http://localhost:$(TADAS_PGWEB_PORT)"
	@echo "  Valkey Admin   http://localhost:$(TADAS_VALKEY_ADMIN_PORT)"
	@echo "  ElasticMQ UI   http://localhost:$(TADAS_ELASTICMQ_UI_PORT)"
	@echo "  Grafana        http://localhost:$(TADAS_GRAFANA_PORT)   metrics dashboards, no sign-in"
	@echo "  Prometheus     http://localhost:$(TADAS_PROMETHEUS_PORT)"
	@echo "  Jaeger         http://localhost:$(TADAS_JAEGER_PORT)"
	@echo "  GlitchTip      http://localhost:$(TADAS_GLITCHTIP_PORT)   admin@example.test / tadas-local"
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

# The SEED_* values come from .env (or .env.example); override any of them
# there or on the command line, e.g. `make seed SEED_EMAIL=me@example.test`.
seed: ## Create a local org with an owner and a member to sign in as; a no-op once they exist
	uv run --package tadas-api tadas-api bootstrap --if-absent \
		--org "$(SEED_ORG)" --slug "$(SEED_SLUG)" --name "$(SEED_NAME)" \
		--email "$(SEED_EMAIL)" --password "$(SEED_PASSWORD)"
	uv run --package tadas-api tadas-api add-member --slug "$(SEED_SLUG)" \
		--name "$(SEED_MEMBER_NAME)" --email "$(SEED_MEMBER_EMAIL)" --password "$(SEED_PASSWORD)"

# Needs `make up` (the seeded owner and member, the API on 8000, the portal on
# 55173). Empties the task list, then records docs/media/realtime-demo.gif.
demo-gif: ## Record the README's realtime demo GIF against the running stack
	uv run --with pillow python scripts/record_demo.py docs/media/realtime-demo.gif

# Needs `make up` too. Bob in command mode on the left, the owner on
# `tadas listen` on the right; records docs/media/cli-demo.gif.
demo-cli-gif: ## Record the README's CLI demo GIF (command mode beside listen) against the running stack
	uv run --with pillow python scripts/record_cli_demo.py docs/media/cli-demo.gif

# The ORM-versus-schema check needs a migrated database, which the fast gate
# cannot reach, so `check` does not run it; CI's integration job runs it
# right after `make migrate`, and the downgrade-then-upgrade round trip stays
# in the integration tests. The deviation is ADR 0003.
migrate-check: ## Compare every role's ORM metadata with the migrated schema
	uv run --package tadas-om python -m tadas.om.storage.migrate check --all

# What a process pays to boot: imports once, then microseconds per root (ADR 0007).
bench-boot: ## Time the imports and the construction of every root
	uv run --package tadas-api python scripts/bench_boot.py

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

# One committed document, apps/portal/openapi.json; both generated type sets
# come from it: the portal's schema.d.ts and the Python client's schema.py.
openapi: ## Emit the API document and regenerate the portal's and the Python client's types
	uv run --package tadas-api tadas-api openapi --out apps/portal/openapi.json
	pnpm --filter @tadas/portal generate
	uv run datamodel-codegen --input apps/portal/openapi.json --input-file-type openapi \
		--output clients/python/src/tadas/client/schema.py \
		--output-model-type pydantic_v2.BaseModel --target-python-version 3.13 \
		--use-standard-collections --use-union-operator --use-annotated \
		--enum-field-as-literal none --use-schema-description --disable-timestamp \
		--formatters ruff-format --formatters ruff-check
