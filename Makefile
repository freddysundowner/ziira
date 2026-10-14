.PHONY: setup db-up db-down install run test lint check web-setup web web-check api-types e2e-setup e2e

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

lint:             ## style, types and module boundaries
	.venv/bin/ruff check ziira tests
	.venv/bin/mypy ziira
	.venv/bin/lint-imports

check: lint test

web-setup:        ## install the web app's packages
	npm --prefix frontend ci

web:              ## start the web app on http://localhost:5173 (needs the API on :8000)
	npm --prefix frontend run dev

web-check:        ## web app: lint, types, tests, build
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck
	npm --prefix frontend test
	npm --prefix frontend run build

api-types:        ## regenerate the web app's API types after changing backend routes or schemas
	.venv/bin/python scripts/export_openapi.py
	npm --prefix frontend run api

e2e-setup:        ## real-browser tests: install Playwright and its Chromium (once)
	cd e2e && npm ci && npx playwright install chromium

e2e:              ## real-browser journeys against a throwaway stack (scratch databases, API on :8765, web on :4175); see docs/testing.md
	bash e2e/run.sh
