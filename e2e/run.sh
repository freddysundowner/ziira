#!/usr/bin/env bash
# End-to-end tests in a real browser against a throwaway stack. Usage: bash e2e/run.sh [playwright args]
# Starts: scratch PostgreSQL databases (ziira_e2e_*, never the dev, demo or pytest ones), the API on :8765 and the
# built web app (vite preview) on :4175; runs Playwright; stops everything and drops the scratch databases.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
API_PORT="${E2E_API_PORT:-8765}"
WEB_PORT="${E2E_WEB_PORT:-4175}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ziira-e2e.XXXXXX")"
PIDS=()

# One end-to-end run at a time (the scratch databases and ports are fixed): later runs wait here
exec 9>"${TMPDIR:-/tmp}/ziira-e2e.lock"
.venv/bin/python -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX)'

set -a; [ -f .env ] && . ./.env; set +a
ADMIN="${ZIIRA_TEST_ADMIN_URL:-postgresql+psycopg://ziira:ziira@localhost:${ZIIRA_DB_PORT:-5432}/postgres}"
export ZIIRA_TEST_ADMIN_URL="$ADMIN"
export ZIIRA_ENV=development ZIIRA_MFA_DEFAULT_POLICY=off
export ZIIRA_MASTER_DATABASE_URL="${ADMIN%/*}/ziira_e2e_master"
export ZIIRA_TENANT_SERVER_URL="$ADMIN"
export ZIIRA_TEMPLATE_DATABASE=ziira_e2e_template ZIIRA_TENANT_DB_PREFIX=ziira_e2e_t_ ZIIRA_TENANT_ROLE_PREFIX=ze2e_
export ZIIRA_DEV_TENANT_HEADER=false
unset ZIIRA_DEV_DEFAULT_TENANT
export ZIIRA_REGISTRATION_MODE=open ZIIRA_REGISTRATION_PER_EMAIL_PER_HOUR=1000 ZIIRA_REGISTRATION_PER_IP_PER_HOUR=1000
export ZIIRA_PUBLIC_WEB_URL="http://localhost:$WEB_PORT"
export ZIIRA_PLATFORM_EMAIL_PROVIDER= ZIIRA_API_URL="http://localhost:$API_PORT"
# Sign-in throttling would lock the browser out after the deliberate wrong-password test
export ZIIRA_THROTTLE_LOGIN_IP_FAILURES=1000 ZIIRA_THROTTLE_LOGIN_FAILURES=1000 ZIIRA_THROTTLE_IP_FAILURES=1000

cleanup() {
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null; done
  sleep 1
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null; done
  .venv/bin/python e2e/scratch_db.py drop 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT
trap "exit 130" INT
trap "exit 143" TERM

for p in "$API_PORT" "$WEB_PORT"; do
  lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && { echo "Port $p is busy"; exit 2; }
done

echo "==> Scratch databases"
.venv/bin/python e2e/scratch_db.py create || exit 2
.venv/bin/ziira install --all >"$WORK/install.log" 2>&1 || { cat "$WORK/install.log"; exit 2; }

# A member of platform staff for the support-access journey (J16): the command prints the second-factor secret once
OPERATOR_PASSWORD="operator-pass-123"
OPERATOR_OUT="$(ZIIRA_OPERATOR_PASSWORD="$OPERATOR_PASSWORD" .venv/bin/ziira operator create "E2E Operator" e2e-operator@ziira.test 2>&1)" || { echo "$OPERATOR_OUT"; exit 2; }
export E2E_OPERATOR_EMAIL=e2e-operator@ziira.test E2E_OPERATOR_PASSWORD="$OPERATOR_PASSWORD"
E2E_OPERATOR_SECRET="$(printf '%s\n' "$OPERATOR_OUT" | sed -n 's/^secret: //p')"
export E2E_OPERATOR_SECRET

echo "==> Building the web app"
[ -d frontend/node_modules ] || npm --prefix frontend ci
(cd frontend && npx vite build --outDir "$WORK/web" --emptyOutDir >"$WORK/build.log" 2>&1) || { cat "$WORK/build.log"; exit 2; }

echo "==> Starting the API on :$API_PORT and the web app on :$WEB_PORT"
.venv/bin/python -m uvicorn ziira.kernel.app:app --port "$API_PORT" --log-level warning >"$WORK/api.log" 2>&1 &
PIDS+=($!)
.venv/bin/ziira worker >"$WORK/worker.log" 2>&1 &      # background jobs (imports, prompts), the outbox and recurring tasks
PIDS+=($!)
(cd frontend && exec node node_modules/vite/bin/vite.js preview --outDir "$WORK/web" --port "$WEB_PORT" --strictPort >"$WORK/web.log" 2>&1) &
PIDS+=($!)
for _ in $(seq 1 60); do
  curl -fs "http://localhost:$API_PORT/health" >/dev/null 2>&1 && curl -fs "http://localhost:$WEB_PORT/" >/dev/null 2>&1 && break
  sleep 1
done
curl -fs "http://localhost:$WEB_PORT/" >/dev/null || { echo "Web app did not start"; cat "$WORK/web.log" "$WORK/api.log"; exit 2; }

if [ -n "${E2E_SERVE:-}" ]; then echo "==> Stack is up (web $WEB_PORT, api $API_PORT); Ctrl+C or kill to stop"; while true; do sleep 5; done; fi
echo "==> Running the tests"
cd e2e
export E2E_BASE_URL="http://localhost:$WEB_PORT" E2E_API_URL="http://localhost:$API_PORT"
npx playwright test "$@"
STATUS=$?
if [ $STATUS -ne 0 ] && [ -s "$WORK/api.log" ]; then echo "--- API log (tail)"; tail -n 40 "$WORK/api.log"; fi
exit $STATUS
