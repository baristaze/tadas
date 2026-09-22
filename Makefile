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
# The one switch between hosts: on Linux, host.docker.internal is the bridge
# gateway, which a process on 127.0.0.1 never answers, so the devx collector
# that scrapes the host processes joins the host's network there.
COMPOSE_LINUX := $(if $(filter Linux,$(shell uname -s)),-f deployment/local/docker-compose.linux.yml)
COMPOSE ?= docker compose $(COMPOSE_ENV) -f deployment/local/docker-compose.yml $(COMPOSE_LINUX)
COMPOSE_FULL := $(COMPOSE) -f deployment/local/docker-compose.full.yml
ROLES := core activity queue admin
# The traffic run's knobs: `make traffic PROFILE=light DURATION=30`.
PROFILE ?= light
DURATION ?= 30

# The guideline's static checker, at the tag of the guideline this project
# follows, on the project's Python: the checker refuses a Python older than
# .python-version. Offline, point it at a checkout:
# `make arch-check ARCH_CHECK="python3 ../swe_guidelines/checkers/arch_check.py"`.
ARCH_CHECK ?= uvx --python "$(shell cat .python-version)" --from "git+https://github.com/baristaze/swe_guidelines@v0.28.0\#subdirectory=checkers" arch-check

.PHONY: help setup up down reset urls infra-up devx-up stack-up infra-down infra-reset migrate seed demo-gif demo-cli-gif migrate-check benchmark-boot check lint format-check typecheck arch-check test-unit test-integration test-telemetry traffic openapi

# This Makefile alone, never $(MAKEFILE_LIST): the includes above put
# .env.example and .env in that list, and grep prefixes every match with the
# file it came from once it is given more than one, so every target would be
# printed under the name "Makefile".
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(firstword $(MAKEFILE_LIST)) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

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

# Names every file and profile so no container of any of them is left behind.
reset: ## Wipe every container and all local data, then `make up`
	$(COMPOSE_FULL) --profile devx down -v --remove-orphans
	$(MAKE) --no-print-directory up

urls: ## Print the local URLs and the seeded sign-ins
	@echo ""
	@echo "  Portal         http://localhost:55173   sign in: $(SEED_EMAIL) or $(SEED_MEMBER_EMAIL) / $(SEED_PASSWORD)"
	@echo "                 two orgs: $(SEED_ADMIN_EMAIL) / $(SEED_PASSWORD)   owner of $(SEED_SECOND_ORG), admin of $(SEED_ORG)"
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

devx-up: ## The local stack plus developer dashboards (pgweb, Valkey Admin, ElasticMQ UI, Prometheus and its collector, Grafana, Jaeger, GlitchTip)
	$(COMPOSE) --profile devx up -d --wait

stack-up: ## The local stack plus the api, maintenance, and portal containers
	$(COMPOSE_FULL) up -d --build --wait

# The shortcuts above are the developer's path; these are the steps they wrap,
# which is what CI and a developer debugging one of them run one at a time.
infra-down: ## Stop the dependencies; the data stays, as after `make down`
	$(COMPOSE) down --remove-orphans

infra-reset: ## Recreate the dependencies with their volumes removed, and nothing else
	$(COMPOSE) down -v --remove-orphans
	$(MAKE) --no-print-directory infra-up

# The local targets (migrate, migrate-check, seed, test-integration) refuse a
# database whose host is not local, so a stray .env never points them at a
# shared one; the cloud runs `tadas-api migrate` without --local.
migrate: ## Apply every role's migration chain to the local database
	uv run --package tadas-om python -m tadas.om.storage.migrate upgrade --all --local

# The SEED_* values come from .env (or .env.example); override any of them
# there or on the command line, e.g. `make seed SEED_EMAIL=me@example.test`.
# The admin owns the second org and joins the first as an admin: one person
# with two memberships, each under a different role.
seed: ## Create two local orgs with an owner, a member, and an admin of both to sign in as; a no-op once they exist
	uv run --package tadas-api tadas-api bootstrap --if-absent \
		--org "$(SEED_ORG)" --slug "$(SEED_SLUG)" --name "$(SEED_NAME)" \
		--email "$(SEED_EMAIL)" --password "$(SEED_PASSWORD)"
	uv run --package tadas-api tadas-api add-member --slug "$(SEED_SLUG)" \
		--name "$(SEED_MEMBER_NAME)" --email "$(SEED_MEMBER_EMAIL)" --password "$(SEED_PASSWORD)"
	uv run --package tadas-api tadas-api bootstrap --if-absent \
		--org "$(SEED_SECOND_ORG)" --slug "$(SEED_SECOND_SLUG)" --name "$(SEED_ADMIN_NAME)" \
		--email "$(SEED_ADMIN_EMAIL)" --password "$(SEED_PASSWORD)"
	uv run --package tadas-api tadas-api add-member --slug "$(SEED_SLUG)" --role admin \
		--name "$(SEED_ADMIN_NAME)" --email "$(SEED_ADMIN_EMAIL)" --password "$(SEED_PASSWORD)"

# Needs `make up` (the seeded owner and member, the API on 8000, the portal on
# 55173). Empties the task list, then records docs/media/realtime-demo.gif:
# Bob's window on the left, the owner's on the right.
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
	uv run --package tadas-om python -m tadas.om.storage.migrate check --all --local

# What a process pays to boot: imports once, then microseconds per root (ADR 0007).
benchmark-boot: ## Time the imports and the construction of every root
	uv run --package tadas-api python scripts/benchmark_boot.py

check: lint format-check typecheck arch-check test-unit ## The fast local gate
	@if [ -d apps ]; then pnpm run lint && pnpm run typecheck && pnpm run test; fi

lint: ## Ruff lint
	uv run ruff check .

format-check: ## Ruff format, check only
	uv run ruff format --check .

typecheck: ## Pyright over every distribution
	uv run pyright

arch-check: ## The guideline's static checks, configured in pyproject.toml
	$(ARCH_CHECK)

test-unit: ## Unit tests over the memory impls
	uv run pytest -q -m "not integration and not e2e and not telemetry"

test-integration: ## Integration tests over the compose stack
	uv run pytest -q -m integration

# The round trip: a real API process on 8000 (the host target the devx
# collector scrapes and writes into Prometheus) with the exporter and the DSN set, one session of traffic, then
# every signal read back by request id through the devx stores. Needs
# `make devx-up` and `make migrate seed`; skips, naming why, when it cannot.
test-telemetry: ## The telemetry round trip over the devx profile
	uv run pytest -q -m telemetry

# The gate's sanity run: the light profile for thirty seconds over the seeded
# org, against the API on 8000. Proves the wiring, says nothing about capacity.
traffic: ## Drive light traffic at the local API (PROFILE=light DURATION=30)
	uv run tadas-ops traffic --env local --profile $(PROFILE) --duration $(DURATION) --orgs 0

# One committed document, apps/portal/openapi.json; both generated type sets
# come from it: the portal's schema.d.ts and the Python client's schema.py.
openapi: ## Emit the API document and regenerate the portal's and the Python client's types
	uv run --package tadas-api tadas-api openapi --out apps/portal/openapi.json
	pnpm --filter @tadas/portal generate
	uv run datamodel-codegen --input apps/portal/openapi.json --input-file-type openapi \
		--output clients/python/src/tadas/client/schema.py \
		--output-model-type pydantic_v2.BaseModel --target-python-version 3.14 \
		--use-standard-collections --use-union-operator --use-annotated \
		--enum-field-as-literal none --use-schema-description --disable-timestamp \
		--formatters ruff-format --formatters ruff-check
