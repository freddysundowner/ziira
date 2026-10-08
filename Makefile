.PHONY: setup db-up db-down install run test lint check

PY ?= python3

setup:            ## create the virtual environment and install everything
	$(PY) -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env

db-up:            ## start PostgreSQL and Redis in Docker
	docker compose up -d
	@echo "Waiting for PostgreSQL..."; until docker compose exec -T db pg_isready -U ziira >/dev/null 2>&1; do sleep 1; done

db-down:
	docker compose down

install:          ## install the kernel and every module and plugin into the database
	.venv/bin/ziira install --all

run:              ## start the API on http://localhost:8000 (docs at /docs)
	.venv/bin/uvicorn ziira.kernel.app:app --reload

test:             ## run all tests (creates and drops the ziira_test database)
	set -a; [ -f .env ] && . ./.env; set +a; .venv/bin/pytest -q

lint:
	.venv/bin/ruff check ziira tests
	.venv/bin/lint-imports

check: lint test
