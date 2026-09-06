SHELL := /bin/bash
COMPOSE := docker compose

# `python` is not on PATH on a stock macOS or Debian box, and the system
# interpreter is often too old for these services. `make install` creates a
# per-service virtualenv; the targets below prefer it and fall back to PYTHON
# so a developer with their own environment activated is not overridden.
PYTHON ?= python3
ANALYSER_PY := $(if $(wildcard services/analyser/.venv/bin/python),../../services/analyser/.venv/bin/python,$(PYTHON))
INSIGHTS_PY := $(if $(wildcard services/insights/.venv/bin/python),../../services/insights/.venv/bin/python,$(PYTHON))

.DEFAULT_GOAL := help

.PHONY: help up down logs db-reset psql seed test test-ingestion test-analyser test-insights install check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the full stack
	$(COMPOSE) up --build -d
	@echo "ingestion  -> http://localhost:$${INGESTION_PORT:-3000}/docs"
	@echo "analyser   -> http://localhost:$${ANALYSER_PORT:-8001}/docs"
	@echo "insights   -> http://localhost:$${INSIGHTS_PORT:-8002}/docs"

down: ## Stop the stack (keeps the database volume)
	$(COMPOSE) down

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

db-reset: ## Destroy the database volume and re-run migrations from scratch
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres
	@echo "Postgres recreated; db/migrations re-applied via docker-entrypoint-initdb.d"

psql: ## Open a psql shell against the running database
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-kybershield} -d $${POSTGRES_DB:-kybershield}

install: ## Install local dev dependencies for every service
	cd services/ingestion && npm ci
	cd services/analyser && $(PYTHON) -m venv .venv && .venv/bin/python -m pip install -q -e ../../packages/pycommon -e '.[dev]'
	cd services/insights && $(PYTHON) -m venv .venv && .venv/bin/python -m pip install -q -e ../../packages/pycommon -e '.[dev]'

seed: ## Post a realistic mixed event stream at the running ingestion service
	cd services/ingestion && npm run seed

test: test-ingestion test-analyser test-insights ## Run every test suite

test-ingestion: ## Run the ingestion test suite
	cd services/ingestion && npm test

test-analyser: ## Run the analyser test suite
	cd services/analyser && $(ANALYSER_PY) -m pytest

test-insights: ## Run the insights test suite
	cd services/insights && $(INSIGHTS_PY) -m pytest

# Lint and typecheck. Separate from `test` because it needs no database, so it
# is the fast feedback loop and the one a reviewer can run on a clean checkout.
check: ## Lint and typecheck every service (no database needed)
	cd services/ingestion && npm run typecheck
	cd services/analyser && $(ANALYSER_PY) -m ruff check .
	cd services/insights && $(INSIGHTS_PY) -m ruff check .
