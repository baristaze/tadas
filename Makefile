# Tadas developer entry points. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose -f deployment/local/docker-compose.yml
ROLES := core activity queue admin

.PHONY: help setup infra-up infra-down migrate check lint format-check typecheck test-unit test-integration openapi

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install every Python and TypeScript dependency
	uv sync --all-packages
	@if [ -f pnpm-workspace.yaml ] && [ -d apps ]; then pnpm install; fi

infra-up: ## Start Postgres, the cache, the queue, and the object store
	$(COMPOSE) up -d --wait

infra-down: ## Stop the local stack and drop its volumes
	$(COMPOSE) down -v

migrate: ## Apply every role's migration chain to the local database
	uv run --package tadas-om python -m tadas.om.storage.migrate upgrade --all

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
	uv run --package tadas-api tadas-api openapi --out packages/api-client/openapi.json
	pnpm --filter @tadas/api-client generate
