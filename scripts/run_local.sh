#!/usr/bin/env bash
# Run Ziira Core locally on a Mac in one step:
#   bash scripts/run_local.sh
# Finds Python 3.12+, starts PostgreSQL (Docker, or a local install), installs all
# tables, creates a demo tenant with sample products, and starts the API on port 8000.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31mStopped: %s\033[0m\n' "$1"; exit 1; }

# Common install locations that may not be on PATH
export PATH="$HOME/.pyenv/shims:$HOME/.homebrew/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"

# ---------------------------------------------------------------- Python
say "Looking for Python 3.12 or newer"
PY=""
for c in python3.14 python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  for p in "$HOME"/.pyenv/versions/3.1[2-9]*/bin/python3; do [ -x "$p" ] && PY="$p" && break; done
fi
[ -n "$PY" ] || fail "Python 3.12+ not found. Install it with:  brew install python@3.12"
echo "Using $PY ($("$PY" --version))"

say "Installing Python packages"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -e ".[dev]"

# ---------------------------------------------------------------- PostgreSQL
say "Starting the database"
# Port from .env (ZIIRA_DB_PORT), e.g. 5433 when another PostgreSQL already uses 5432
DB_PORT="$(grep -E '^ZIIRA_DB_PORT=' .env 2>/dev/null | cut -d= -f2 || true)"
DB_PORT="${DB_PORT:-5432}"
MASTER_URL="postgresql+psycopg://ziira:ziira@localhost:$DB_PORT/ziira_master"
SERVER_URL="postgresql+psycopg://ziira:ziira@localhost:$DB_PORT/postgres"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Using Docker"
  docker compose up -d db
  for _ in $(seq 1 60); do docker compose exec -T db pg_isready -U ziira >/dev/null 2>&1 && break; sleep 1; done
  docker compose exec -T db pg_isready -U ziira >/dev/null 2>&1 || fail "PostgreSQL in Docker did not start"
elif command -v psql >/dev/null 2>&1; then
  echo "Using the PostgreSQL installed on this Mac"
  pg_isready -h localhost -p "$DB_PORT" >/dev/null 2>&1 || {
    command -v brew >/dev/null 2>&1 && brew services start postgresql@16 >/dev/null 2>&1 || true
    sleep 3
  }
  pg_isready -h localhost -p "$DB_PORT" >/dev/null 2>&1 || fail "PostgreSQL is not running on port $DB_PORT. Start it (Postgres.app, or: brew services start postgresql@16)"
  psql -h localhost -p "$DB_PORT" -d postgres -v ON_ERROR_STOP=1 -q <<'SQL'
do $$ begin
  if not exists (select from pg_roles where rolname = 'ziira') then
    create role ziira login password 'ziira' createdb createrole; end if;
end $$;
SQL
else
  fail "No database found. Either open Docker Desktop, or install PostgreSQL:  brew install postgresql@16 && brew services start postgresql@16"
fi

# ---------------------------------------------------------------- Settings
[ -f .env ] || cp .env.example .env
export ZIIRA_MASTER_DATABASE_URL="$MASTER_URL" ZIIRA_TENANT_SERVER_URL="$SERVER_URL"

say "Setting up the master database and the tenant template"
.venv/bin/ziira install --all

say "Creating demo data"
TENANT="$(.venv/bin/python scripts/seed_demo.py | tail -1)"
grep -q '^ZIIRA_DEV_DEFAULT_TENANT=' .env \
  && sed -i '' "s/^ZIIRA_DEV_DEFAULT_TENANT=.*/ZIIRA_DEV_DEFAULT_TENANT=$TENANT/" .env \
  || echo "ZIIRA_DEV_DEFAULT_TENANT=$TENANT" >> .env
echo "Demo tenant: $TENANT"

# ---------------------------------------------------------------- Server
PORT=8000
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then PORT=8010; fi
say "Ziira Core is running:  http://localhost:$PORT/docs     (Ctrl+C to stop)"
echo "Sign in: workspace demo-hardware · owner@demo-hardware.test · demo-pass-123"
exec .venv/bin/uvicorn ziira.kernel.app:app --port "$PORT" --reload
