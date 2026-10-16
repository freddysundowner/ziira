.PHONY: deploy-test deploy-test-docker setup db-up db-down install run test lint check web-setup web web-check api-types e2e-setup e2e site-setup site site-catalog site-build site-check site-screens

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

site-setup:       ## marketing website (site/): npm ci
	cd site && npm ci

site:             ## marketing website dev server on http://localhost:4321
	cd site && npm run dev

site-catalog:     ## marketing website: regenerate site/src/content/checks.catalog.json (checks, actions, ask tools) from the real registry
	.venv/bin/python scripts/export_check_catalog.py

site-build: site-catalog  ## marketing website: static build into site/dist (warns loudly if PUBLIC_SITE_URL is unset)
	cd site && npm run build

site-check: site-catalog  ## marketing website: unit tests, build, SEO audit, link check; warns (not fails) on stale screenshots (docs/marketing-site.md)
	cd site && npm test && npm run build && npm run seo:check && npm run links:check

site-screens:     ## marketing website: re-capture every product screenshot from the RUNNING app (:5173 + API :8000, demo business), then rebuild the optimised assets
	cd site && node scripts/capture-screens.mjs && npm run build && npm run responsive

deploy-test:      ## production installer kit (deploy/): unit tests with a fake server, ruff
	.venv/bin/ruff check deploy
	.venv/bin/python -m pytest deploy/tests -q

deploy-test-docker: ## installer config-only run in a throwaway Ubuntu 24.04 container with a real nginx (needs Docker)
	bash deploy/tests/docker/run.sh
