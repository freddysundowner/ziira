# Operations

Running Ziira Core: environments, releases, backups and recovery, monitoring, logging, connection pooling, incidents.
Specification: `docs/specs/Ziira_Core_1.0_Technical_Specification.txt` section 19 (infrastructure) and the "Application
security" and "Logging" rows of section 18. Application security controls themselves (sign-in, MFA, tenancy) are in
`docs/security.md`.

Hosting is "a VPS": this document names no provider. Where a step needs something on the server (a reverse proxy,
a scheduler, object storage), it says what, not whose.

## What is built and what you must set up

| Area | Built into the code (tested) | The operator must do (not in the code, **not tested here**) |
|---|---|---|
| Health | `GET /healthz` (liveness), `GET /readyz` (master database, template, migrations), `GET /metrics` | Point the load balancer / uptime checks at them |
| Metrics | In-process request counts and latency histogram; queue, outbox, periodic task, notification and Intelligence gauges across all businesses, cached 15 s | Run Prometheus (or any scraper of the text format), dashboards, alert routing to on-call |
| Logging | Request id, tenant id, JSON or text lines, secret redaction, one access line per request | Ship logs off the server, retain and protect them |
| HTTP hardening | Security headers, no-store on API replies, CORS allowlist, body size limit, HSTS in production | TLS termination, the static site's headers (below), rate limiting at the proxy, a WAF if wanted |
| Backups | `ziira backup` (pg_dump per database + manifest + retention), `ziira restore-test`, `ziira restore` (into a new database only) | **Schedule them**, copy dumps off the server, encrypt them, **WAL archiving** for point-in-time recovery, store `ZIIRA_CREDENTIALS_KEY` separately |
| Pooling | Pool settings, capped engine cache, PgBouncer-safe session handling (`ZIIRA_PGBOUNCER`), statement timeout | Run PgBouncer, its `auth_query`, sizing |
| CI | `pip-audit`, `npm audit`, secret scan (`.github/workflows/security.yml`), `scripts/check_env.py` | Read the results, act on them |
| Incidents | (nothing) | The response plan below, contact list, on-call rota, legal notification |

## Environments

Development, staging and production are fully separate: their own databases, their own `ZIIRA_SECRET_KEY` and
`ZIIRA_CREDENTIALS_KEY`, their own provider accounts.

| | Development | Staging | Production |
|---|---|---|---|
| `ZIIRA_ENV` | `development` | `production` | `production` |
| Data | demo business, fake | copy of nothing real (seeded, or anonymised) | customers |
| Daraja / eTIMS / SMS | sandboxes or fakes | **sandboxes** (the spec requires staging to have them) | live |
| Dev header (`ZIIRA_DEV_TENANT_HEADER`) | true | **false** | **false** |
| Registration | open | as production | `invite` or `closed` until the email provider is proven |

Staging runs with `ZIIRA_ENV=production` on purpose, so it exercises the same start-up refusals and headers (HSTS,
`/metrics` refusing without a token) as production.

**Check the configuration before every deployment:**

```bash
python scripts/check_env.py /path/to/production.env       # exit 1 on any ERROR
```

It checks: production mode, both keys set, long, random, different from each other and from the development values;
the development header off; database passwords not the defaults; https public addresses; registration consistent with
an email provider (valid JSON secret and config); a metrics token; CORS origins exact (never `*`); the MFA default
policy; and warns about text logs, open registration and `TRUST_FORWARDED_FOR`. It connects to nothing. The
application re-checks the essentials when it starts (`Settings.check_safe_for_production`).

Generate a key: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## Deploying

Containers (the repository has no Dockerfile yet; the shape below is what the code expects):

| Container | Command | Replicas |
|---|---|---|
| `api` | `uvicorn ziira.kernel.app:app --host 0.0.0.0 --port 8000 --workers 2 --timeout-keep-alive 5 --timeout-graceful-shutdown 30 --proxy-headers` | 2 or more behind the proxy (stateless) |
| `worker` | `ziira worker` (events, background jobs, recurring tasks, purge) | 1 is enough; 2 is safe (rows are claimed with `SKIP LOCKED`) |
| `web` | static files from `npm --prefix frontend run build` (`frontend/dist`) | served by the reverse proxy |
| `postgres` | PostgreSQL 16 (or a managed equivalent) | 1 primary (+ replica for reports later) |
| `pgbouncer` | optional, see "Connection pooling" | 1 |
| `proxy` | TLS, headers for the web app, forwards `/api` and the probes to `api` | 1 |

Release steps, in this order (the spec: tests, migrations, deploy; zero downtime; migrations backward-compatible for
one release):

1. CI is green on the commit (lint, mypy, import-linter, tests, security workflow).
2. `python scripts/check_env.py` on the production configuration.
3. **Take a backup** (`ziira backup --dir ...`) and confirm it succeeded. Skip only for a hotfix with no migrations.
4. Build the images and push them.
5. **Run migrations from the new image, before any new `api` container takes traffic:**
   `ziira install --all` (applies the master migrations, the template's, and every unit's new migrations in every
   tenant database; it is idempotent). The old `api` containers are still serving at this moment, which is why a
   migration must be **backward compatible for one release**:
   - release N may add tables, add nullable columns or columns with defaults, add indexes, add permissions;
   - it may not drop or rename anything release N-1 still reads or writes, or add a `NOT NULL` column without a default;
   - drop/rename/constrain in release N+1, once N-1 is gone. Migrations already applied are never edited (new numbered pair).
6. Start the new `api` containers; wait until `GET /readyz` returns 200 on each (it returns 503 with a reason while
   the master migrations or unit versions in the database are behind the code: that is the guard against deploying code
   before step 5); then take the old ones out of the proxy and stop them (finish in-flight requests: 30 s grace).
7. Restart `worker` on the new image.
8. Smoke test: sign in, `/readyz`, one read, check the dashboard of errors for five minutes.
9. **Rollback**: redeploy the previous image (it works because of step 5's rule). Do not run `down` migrations in
   production; a migration that must be undone is undone by a new forward migration.

`/readyz` limits: it checks the master database answers, the master migrations are all applied, the template database
exists and every installed unit has the same version as the code. It does not connect to tenant databases or the
template (connecting to the template would block creating a tenant) and it cannot see a new migration file that came
without a unit version bump: bump the unit's version in `manifest.toml` with its migration.

### Timeouts and limits (all documented, most are settings)

| Layer | Setting | Default | Notes |
|---|---|---|---|
| Proxy | read / send timeout | 60 s (set it) | longer than the slowest legitimate report, shorter than clients wait |
| Proxy | request body size | 5 MB (set it) | the API's own limit is lower |
| uvicorn | `--timeout-keep-alive` | 5 s | |
| uvicorn | `--timeout-graceful-shutdown` | 30 s | in-flight requests finish on deploy |
| API | `ZIIRA_MAX_BODY_BYTES` | 2,000,000 | `413 too_large`; also for bodies sent chunked without a length |
| Database | `ZIIRA_STATEMENT_TIMEOUT_MS` | 60,000 | per statement, tenant sessions only (migrations and provisioning use the admin login and are unlimited); 0 switches it off |
| Database | `ZIIRA_DB_POOL_TIMEOUT` | 30 s | waiting for a free pooled connection |
| Database | `ZIIRA_DB_POOL_RECYCLE` | 1800 s | connections older than this are replaced |
| Outbound | provider calls (Daraja, SMS, email) | each provider's own `httpx` timeout | see `payments/providers.py` |

There is no per-request time limit inside the application: the proxy and the statement timeout bound a request.

## Application security plumbing

Everything here is done by `ziira/kernel/http_middleware.py` (one pure-ASGI middleware, outermost) and
`ziira/kernel/app.py`, and is covered by `tests/test_ops.py`.

| Header / behaviour | Value |
|---|---|
| `X-Request-ID` | accepted from the caller if 8-128 characters of `A-Za-z0-9._-`, else created; returned on every response, in every error body (`request_id`), and in the logs |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()` (the API serves no pages; if the cashier terminal later scans barcodes with the camera, allow `camera=(self)` **on the static site**, not here) |
| `Cross-Origin-Opener-Policy` / `Cross-Origin-Resource-Policy` | `same-origin` / `same-site` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` on every API response **except** `/`, `/docs`, `/redoc`, `/openapi.json` (Swagger UI needs its own scripts; switch `/docs` off at the proxy in production) |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` when `ZIIRA_ENV=production` (`ZIIRA_HSTS_MAX_AGE`) |
| `Cache-Control: no-store` (+ `Pragma: no-cache`) | every `/api/...` response and any request carrying `Authorization` or `X-API-Key` |
| CORS | none unless `ZIIRA_CORS_ORIGINS` lists origins (comma separated, exact). No credentials are ever allowed (bearer tokens travel in a header). `*` is refused in production at start-up. Allowed headers: `Authorization, Content-Type, Idempotency-Key, X-API-Key, X-Request-ID, X-Device-ID, Accept-Language` |
| Body size | `ZIIRA_MAX_BODY_BYTES` -> `413 {"error":"too_large"}` |
| Unhandled error | JSON `500 internal_error` with the request id, never a stack trace; the traceback goes to the log (redacted) |
| Client address | `kernel/auth.py client_ip` (unchanged): behind your proxy set `ZIIRA_TRUST_FORWARDED_FOR=true` and make the proxy overwrite `X-Forwarded-For` |

If the web app and the API share one origin (the proxy sends `/api` to the API and everything else to the static
files), no CORS setting is needed at all. That is the recommended layout.

### The static site (what the Vite build serves)

`npm --prefix frontend run build` produces `frontend/dist/`: an `index.html` with **one inline script** (the dark-mode
bootstrap in `frontend/index.html`), hashed JS/CSS files under `/assets/`, no web fonts, no external requests, no
`eval`. Components use `style={{...}}` attributes, so the policy needs `style-src-attr 'unsafe-inline'` (attributes
only; stylesheets stay `'self'`). The API is called on the same origin (`/api`). The proxy should send, for every
response of the static site:

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'sha256-eQtQGoyst61TlDOMudw6dpdpY/pD+ZrRP8eLAxmDq78='; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Cross-Origin-Opener-Policy: same-origin
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

- The `sha256-...` is the hash of the inline script as it is in `frontend/index.html` today. **If you change that
  script, recompute it**: `python3 -c "import re,hashlib,base64;h=open('frontend/index.html').read();print(base64.b64encode(hashlib.sha256(re.search(r'<script>(.*?)</script>',h,re.S).group(1).encode()).digest()).decode())"`.
  (Or move the script to a file in `frontend/public/` and drop the hash.)
- If the API is on another origin, add it to `connect-src` and list the web app's origin in `ZIIRA_CORS_ORIGINS`.
- Downloads use `URL.createObjectURL` + an anchor: allowed by this policy. If a screen ever previews a PDF in a frame,
  add `frame-src blob:`.
- Caching: `index.html` and the probes `no-cache`; `/assets/*` `Cache-Control: public, max-age=31536000, immutable`
  (file names are content hashes); unknown paths fall back to `index.html` (single-page app) with a 200.
- Untested: the policy was derived from reading the build and the source, **not** by loading every screen in a
  browser with it switched on. Run the app with it in `Content-Security-Policy-Report-Only` first and watch the
  browser console on each module's screens.

## Logging

`ZIIRA_LOG_FORMAT=json` (production) or `text` (default), `ZIIRA_LOG_LEVEL` (default `INFO`). The API and
`ziira worker` / `outbox-run` install the same handler (`ziira/kernel/observability.py`). A JSON line:

```json
{"time":"2026-10-14T14:59:39.123+00:00","level":"INFO","logger":"ziira.access","message":"GET /api/v1/exceptions/{item_id} 404 12ms",
 "request_id":"1f0c...","tenant_id":"0c47f3cf-...","route":"/api/v1/exceptions/{item_id}","method":"GET","status":404,
 "duration_ms":12.3,"client":"203.0.113.9","request_bytes":0}
```

- One `ziira.access` line per request, with the **route template** (never the real path with ids in it), the tenant
  once the caller is known, the duration. Probes (`/healthz`, `/readyz`, `/health`, `/metrics`) log at DEBUG.
- **Redaction** is applied to every message, exception text and extra field before it is written (`redact()` in
  `observability.py`; Hypothesis-tested): `Authorization`/Bearer values, our token formats (`zr_`, `zk_`, `zdk_`), the
  value after any key that looks like a password, secret, token, api key, credential, pin, otp, cvv; Luhn-valid card
  numbers; any other run of 9 or more digits (national ids, account and phone numbers; this also hides large numeric
  ids, by design).
- It is a safety net, **not** permission to log bodies or personal data. Do not log request bodies, headers or whole
  objects. Free text in a format it cannot recognise (a password written as a sentence) is not caught.
- Retention is the operator's: suggested 90 days searchable, one year archived, access restricted to on-call staff
  (logs hold client IPs and tenant ids, which are personal data: `docs/privacy.md`).
- Under `uvicorn`, do not pass `--access-log`/`--log-config`; our handler replaces uvicorn's and silences its access log.

## Monitoring and alerting

### Probes

| Probe | Use | Expect |
|---|---|---|
| `GET /healthz` | restart the container if it fails 3 times | 200 `{"status":"ok"}` |
| `GET /readyz` | send traffic only when 200 | 200 `{"status":"ready"}`; 503 `{"problems":[...]}` |
| `GET /metrics` | Prometheus scrape, `Authorization: Bearer $ZIIRA_METRICS_TOKEN` | text format; 401 wrong token; 403 in production with no token set |

Keep `/metrics` and `/readyz` off the public internet if you can (proxy rule or firewall); the token is the second lock.
The token is compared in constant time; rotate it by changing the setting and the scraper together.

### Metrics

HTTP, **per process** (a restart resets them; with several `api` processes scrape each and `sum` in queries):

| Metric | Type | Labels |
|---|---|---|
| `ziira_http_requests_total` | counter | `method`, `route` (template, `unmatched` for 404s), `status` (`2xx`..`5xx`) |
| `ziira_http_request_duration_seconds` | histogram (5 ms .. 10 s) | `method`, `route` |

Platform gauges (across all active businesses, one query each, **cached for `ZIIRA_METRICS_CACHE_SECONDS` = 15 s**;
every `api` process computes its own copy, so scrape these from one instance or accept the repeated query load):

| Metric | Meaning |
|---|---|
| `ziira_tenants{status}` | businesses by status (`provisioning` for long = a failed sign-up) |
| `ziira_jobs_queued`, `ziira_jobs_due`, `ziira_jobs_failed` | background job queue depth, due now, and jobs that used all their attempts |
| `ziira_jobs_oldest_due_seconds` | how long the longest-waiting due job has waited (worker stalled?) |
| `ziira_outbox_pending`, `ziira_outbox_stuck` | events not yet delivered; events that failed all 10 attempts |
| `ziira_outbox_lag_seconds` | age of the oldest undelivered event |
| `ziira_periodic_last_run_age_seconds{task}` | for each recurring task, seconds since the **least recently run** business ran it |
| `ziira_periodic_failing_tenants{task}` | businesses where the task's last run failed |
| `ziira_notifications_queued`, `ziira_notifications_failed` | customer messages waiting / failed |
| `ziira_intel_check_failures` | Intelligence checks that could not run (open items from the last 24 h) |
| `ziira_metrics_tenant_errors` | businesses whose database could not be read for these metrics |
| `ziira_metrics_collect_seconds`, `ziira_metrics_collected_timestamp_seconds` | cost and freshness of the gauges |

Cost: one query per business (about a few milliseconds each on the test database). With hundreds of businesses raise
`ZIIRA_METRICS_CACHE_SECONDS` to 60 and scrape every minute. Tenant engines are cached (LRU), so a scrape across more
businesses than `ZIIRA_MAX_CACHED_TENANT_ENGINES` reopens pools each time; size the cache accordingly.

### What to alert on

Page someone (on-call) for the first group, ticket for the second.

| Alert | Condition (PromQL sketch) | Why |
|---|---|---|
| API down | probe `/healthz` fails 2 min; or `up == 0` | outage |
| Not ready | `/readyz` 503 for 5 min | migrations or master database problem |
| Error rate | `sum(rate(ziira_http_requests_total{status="5xx"}[5m])) / sum(rate(ziira_http_requests_total[5m])) > 0.02` for 5 min | bugs, database trouble |
| Slow | `histogram_quantile(0.95, sum by (le) (rate(ziira_http_request_duration_seconds_bucket[5m]))) > 2` for 10 min | saturation |
| Worker stalled | `ziira_jobs_oldest_due_seconds > 600` or `ziira_outbox_lag_seconds > 300` for 5 min | sales do not reach stock/finance/messages |
| Outbox stuck | `ziira_outbox_stuck > 0` | an event handler keeps failing: books may be behind |
| Sign-in trouble | rate of `4xx` on `/api/v1/auth/sign-in` far above normal; any `429` burst | credential stuffing |
| Backup missing | no successful `ziira backup` in 26 h (alert from your scheduler's exit code or the newest manifest's age) | RPO |
| WAL archiving failing | `pg_stat_archiver.failed_count` rising, or last archived WAL older than 15 min | RPO of 15 minutes |
| Disk | database or backup volume > 80% | outage |
| Failed jobs | `increase(ziira_jobs_failed[1h]) > 0` | integration down (payments, messages) |
| Recurring task late | `ziira_periodic_last_run_age_seconds > 3 * <task interval>` (intervals are in the units' `@periodic` calls; for the Intelligence checks use ~ 26 h) | checks and briefs are not running |
| Recurring task failing | `ziira_periodic_failing_tenants > 0` for 2 runs | |
| Intelligence checks failing | `ziira_intel_check_failures > 0` | owners' alerts silently missing |
| Messages failing | `increase(ziira_notifications_failed[1h]) > 5` | provider credit/credentials |
| Metrics blind spot | `ziira_metrics_tenant_errors > 0`, or the scrape fails | |
| Certificates | expiry < 14 days | outage |
| Restore test | monthly test not recorded by the 5th | untested backups |

Error tracking (exceptions with context) and uptime checks from outside the network are the operator's to add; the
request id in every error body and log line is the join key between a customer report and the log.

## Backups and recovery

Targets from the specification: **data loss no more than 15 minutes (RPO), restore within 4 hours (RTO).** Daily
snapshots kept 35 days, monthly 12 months, WAL archiving for point-in-time recovery, a restore test every month.

Two layers, because they answer different questions:

| Layer | Answers | Built in code? |
|---|---|---|
| **Logical dumps** (`ziira backup`) | "restore one business", "restore to a different server", "is the data restorable at all?" | yes |
| **WAL archiving + base backups** | "go back to 10:42 yesterday", "lose at most 15 minutes" | **no: operator** |

### Logical backups: `ziira backup`

```bash
ziira backup --dir /backups/ziira                       # master + every tenant
ziira backup --tenant demo-hardware --dir /backups/ziira
ziira backup --dir /backups/ziira --keep-daily 35 --keep-monthly 12     # these are the defaults
```

- One `pg_dump --format=custom` per database: `master` (the list of businesses and their *encrypted* connection
  strings) and each business's own database. Files: `<dir>/<target>/<target>-<UTC time>.dump` plus a `.json` manifest:
  database, size, sha256, time, server version, units and latest migration per unit, and a **row count per table taken
  from the same snapshot as the dump** (`pg_export_snapshot` + `--snapshot`), so counts match the dump exactly on a
  busy database.
- Dumps are consistent per database; they are not consistent *across* databases (the master and a business are
  dumped seconds apart; harmless, since the master only lists businesses).
- Retention is applied per target after its backup succeeds: the **newest backup of each of the last 35 days** and the
  **oldest of each of the last 12 calendar months** are kept; the newest backup is always kept
  (`keep_set`, a pure function, property-tested). A target whose backup failed is not pruned.
- Exit code 1 if any target failed (others still run). The password goes to the tools only through the `PGPASSWORD`
  environment variable and is never logged; tool errors are redacted.
- **Tools and version**: `pg_dump` must be the server's major version or newer. If the machine's client is older
  (this Mac has 14, the Docker server is 16), run the tools where the right version is:
  ```
  ZIIRA_PG_DUMP_COMMAND="docker exec -i -e PGPASSWORD ziira-core-db-1 pg_dump"
  ZIIRA_PG_RESTORE_COMMAND="docker exec -i -e PGPASSWORD ziira-core-db-1 pg_restore"
  ZIIRA_PG_TOOL_HOST=localhost      # how the tool reaches PostgreSQL, from where it runs
  ZIIRA_PG_TOOL_PORT=5432
  ```
  The dump is streamed through stdout and the restore through stdin, so any wrapper that passes those works
  (`docker exec -i`, `ssh host pg_dump`, `kubectl exec -i`). `ziira backup` checks the tools and their version first and
  says what is wrong.
- **Connect directly to PostgreSQL, not through PgBouncer** (set `ZIIRA_PG_TOOL_HOST/PORT` if the stored URLs point at the pooler).
- Schedule it (cron or a systemd timer on the host, run as the service user), daily, off-peak:
  `17 2 * * *  cd /srv/ziira && .venv/bin/ziira backup --dir /backups/ziira || alert-me`.
  Then **copy `/backups/ziira` off the server** (object storage or another machine) with a tool that keeps the copy
  read-only to the server, and **encrypt it** (the spec: encryption at rest for backups): a dump holds every business's
  data. Example: `age -r <public key> -o x.dump.age x.dump` or encrypted object storage. None of this is in the code.
- **Keep `ZIIRA_CREDENTIALS_KEY` and `ZIIRA_SECRET_KEY` somewhere other than the backups.** The master dump holds
  each business's database login *encrypted with the credentials key*: without that key the master dump cannot reach
  any business, and the key must not travel with the dump. Store both keys in a secrets manager or sealed envelope
  held by two people. Losing the credentials key locks out every tenant.

### Restoring: three situations

**A. The monthly restore test (no risk to anything live)** — see the runbook below.

**B. One business lost its data (a bug, a mistaken bulk change), the rest is fine.**

1. Decide the moment you want (the newest dump, or one earlier; for a moment between dumps use situation C).
2. Restore the dump into a **new** database; a restore never writes over an existing database:
   ```bash
   ziira restore --tenant acme --dir /backups/ziira --into ziira_t_acme_restored --keep-ownership
   # --file acme-20261012T021700Z.dump  to choose an older one
   ```
   `--keep-ownership` restores owners and the grants to the business's own login (those logins exist on the same
   server). Without it, the copy has no grants and is for inspection only.
3. Check it (`select` counts, run `ziira verify` after the swap on a staging copy first if time allows).
4. To bring it live, in a maintenance window: stop `api` and `worker`; then in `psql` as the admin:
   `select pg_terminate_backend(pid) from pg_stat_activity where datname in ('ziira_t_acme');`
   `alter database ziira_t_acme rename to ziira_t_acme_broken; alter database ziira_t_acme_restored rename to ziira_t_acme;`
   start `api` and `worker`; `ziira verify acme`; keep `_broken` until the customer confirms, then drop it.
   The business's stored connection (master database) names the database `ziira_t_<code>`, which is why the swap is by
   renaming. Work done after the dump (sales, payments) is **not** in it: reconcile with the customer (their M-Pesa
   statements and till reports), and consider copying the missing rows across from `_broken`.
5. This swap is manual on purpose ("restoring over a live tenant must never be implicit"). Not built: a command that
   does it. It has been rehearsed here only as far as `ziira restore --keep-ownership` and the grants test.

**C. Disaster (server lost) or "go back to 10:42": point-in-time recovery from WAL.** Needs the WAL archive below.

1. Provision a server with the same PostgreSQL major version; install the backup tool; restore the cluster to the
   target time (pgBackRest: `pgbackrest --stanza=ziira --type=time "--target=2026-10-14 10:42:00+00" --target-action=promote restore`).
2. Start PostgreSQL, check `select count(*)` on a few tables, point `ZIIRA_MASTER_DATABASE_URL`/`TENANT_SERVER_URL` at it,
   start `api` and `worker` with the **same** `ZIIRA_CREDENTIALS_KEY`, then run `ziira verify`.
3. To rescue one business from a PITR copy without switching the whole service: restore the cluster on a temporary
   server, `ziira backup --tenant acme` there (or `pg_dump -Fc` its database), then continue with situation B.
4. Expected time: the base backup copy dominates; measure it in the quarterly drill (below) and compare with the
   4-hour target. **No timing has been measured for a production-size cluster.** For scale, on a laptop with the
   database in Docker: the largest dev business (a load-test tenant, 181 MB dump) backed up in 33 s, and its full
   restore test (restore, row counts, journal balance, integrity checks, drop) took 2 min 9 s.

### WAL archiving and PITR (operator setup; example only, not run here)

Without it the best case is "lose everything since the last daily dump" (up to 24 hours), which misses the 15-minute
target. Use a tool that archives WAL and takes base backups, verifies them, and restores to a time: **pgBackRest** or
**WAL-G**. Example PostgreSQL settings (`postgresql.conf`), PostgreSQL 16:

```
wal_level = replica
archive_mode = on
archive_command = 'pgbackrest --stanza=ziira archive-push %p'      # or: wal-g wal-push %p
archive_timeout = 300          # force a WAL segment at least every 5 minutes, so the newest archived data is never older than that
max_wal_senders = 5
wal_compression = on
log_checkpoints = on
```

pgBackRest (`/etc/pgbackrest/pgbackrest.conf`), repository on storage off the database server, encrypted:

```
[global]
repo1-path=/var/lib/pgbackrest          # or repo1-type=s3 / sftp with its settings
repo1-retention-full=12                 # monthly full backups, kept 12 months (take them with: pgbackrest --type=full backup)
repo1-retention-diff=35                 # daily differential backups, kept 35 days  (pgbackrest --type=diff backup)
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=<kept in the secrets manager>
compress-type=zst
start-fast=y

[ziira]
pg1-path=/var/lib/postgresql/16/main
```

Schedule: a full backup monthly, a differential daily, WAL continuously. Check `pgbackrest --stanza=ziira check` after
setup and `pgbackrest info` daily (alert on the age of the last archived WAL: > 15 minutes breaks the RPO).
WAL-G equivalents: `wal-g backup-push`, `wal-g delete retain FULL 12`, `wal-g backup-fetch` + `recovery_target_time`.
Archiving needs the database host's disk and bandwidth to keep up with write volume; watch `pg_stat_archiver`.

### The monthly restore test (runbook)

The spec says restore is tested monthly; the phase 11 exit criterion is "restore test passes". Do this on the first
working day of each month, by the person on the rota, and record the result in the operations log.

1. On a machine that is **not** the production database server, with a copy of last night's backups fetched from the
   off-site store and decrypted: `ls /restore-test/` shows one folder per business plus `master`.
2. Run `ziira restore-test --dir /restore-test` (one business: `--tenant CODE`).
   For each target it: verifies the dump against the manifest's sha256; creates a scratch database
   (`ziira_restore_<random>`); `pg_restore`s into it; compares **every table's row count with the manifest**; checks
   that **every journal entry balances**; runs the **integrity checks** of every unit in it (stock balances against the
   movements, books against the stock ledger, ...); and drops the scratch database whatever happened.
   Exit 0 only if every target passed.
3. Failure handling: a checksum failure means the off-site copy is damaged (re-fetch; if the original is damaged too,
   take a fresh backup now and investigate the storage). A row-count difference means the dump is not what was
   backed up (stop and investigate before the next release). An integrity-check line means the **live data had that
   problem when it was backed up**: the test is reporting a real defect; run `ziira verify <code>` on production.
4. Also, once: restore the *master* dump and one business on a clean server using only the off-site copy, the two keys
   from the secrets manager, and this document. That proves the keys and the procedure, not just the files.
5. Quarterly: a full disaster drill of situation C (PITR to a chosen time), timed against the 4-hour target.
6. Record: date, who, the output, time taken, problems, follow-ups. A month without a recorded pass is an alert.

### Known limits

- `ziira backup` reads all rows of every table to count them: on a very large business consider running it from a
  replica (not supported by the current connection settings: it connects to the stored admin URL).
- Per-table counts of tables that change during the snapshot are exact (same snapshot); files outside the database
  (`kernel.file` content, if stored on disk later) are not covered.
- Dumps of a business restore without its login's password: restored logins and passwords live in the cluster, not
  the database. On a *new* server the business's login role does not exist; for that case use situation C (a cluster
  restore brings the roles) or recreate roles from the master record (not built).

## Connection pooling (PgBouncer)

The application works **without** a pooler (each tenant database has a small SQLAlchemy pool) and **with PgBouncer in
transaction pooling mode**. Settings:

| Setting | Default | Meaning |
|---|---|---|
| `ZIIRA_DB_POOL_SIZE` | 2 | steady connections per cached tenant database |
| `ZIIRA_DB_MAX_OVERFLOW` | 8 | extra connections under load per cached tenant database |
| `ZIIRA_DB_POOL_TIMEOUT` | 30 | seconds to wait for a free connection before failing |
| `ZIIRA_DB_POOL_RECYCLE` | 1800 | replace connections older than this |
| `ZIIRA_MASTER_POOL_SIZE` | 5 | master database pool |
| `ZIIRA_MAX_CACHED_TENANT_ENGINES` | 25 | how many tenant databases keep a pool at once; the least recently used pool is closed (its idle connections released, in-flight work finishes) and reopens on demand |
| `ZIIRA_PGBOUNCER` | false | `true` turns off psycopg's server-side prepared statements (a transaction pooler gives each transaction a different server connection, where a prepared statement would not exist) |
| `ZIIRA_STATEMENT_TIMEOUT_MS` | 60000 | per-statement limit, set with `SET LOCAL`-style `set_config(..., true)` per transaction |

Sizing: worst case server connections = `ZIIRA_MAX_CACHED_TENANT_ENGINES x (POOL_SIZE + MAX_OVERFLOW)` per API process
(default 25 x 10 = 250), times the number of API processes, plus the worker, plus admin use. PostgreSQL's
`max_connections` (default 100) is smaller than that on purpose: either lower the numbers
(`MAX_CACHED_TENANT_ENGINES=10`, `POOL_SIZE=1`, `MAX_OVERFLOW=4`) or put PgBouncer in front.

**Session state: what would break a transaction pooler, and what we found.** Everything below was checked in the code
(`ziira/kernel/db.py` and a search of the whole tree):

- `app.tenant_id` (row-level security) and `statement_timeout` are set with `set_config(name, value, true)`: the third
  argument makes them **transaction-local**, so they vanish at commit/rollback and never leak to the next user of a
  pooled connection. (Covered by `tests/test_db_pooling.py::test_nothing_is_left_on_the_connection_between_transactions`:
  one physical connection serves two transactions and the second sees nothing of the first.)
- Advisory locks are all `pg_advisory_xact_lock` (transaction-scoped): safe. A session-level `pg_advisory_lock` would
  break pooling; none exists.
- No `LISTEN/NOTIFY`, no temporary tables, no `SET ROLE`, no `SET SESSION`, no cursors held across transactions, no
  `WITH HOLD`. Server-side prepared statements are the only session-level feature in use: `ZIIRA_PGBOUNCER=true` removes them.
- Code that **commits in the middle of a request** would lose `app.tenant_id` for the rest of that request (it is set
  once at the start of `tenant_session`). That is true with or without a pooler; services do not do it today.
- Things that must connect **directly** to PostgreSQL, not through the pooler: `pg_dump`/`pg_restore` (`ZIIRA_PG_TOOL_HOST/PORT`),
  `CREATE/DROP DATABASE` and role creation during provisioning (they use the tenant server URL; plain `CREATE DATABASE`
  works through a pooler only on the admin database, so keep that URL direct), and WAL tooling.

Example `pgbouncer.ini` (untested here: **no PgBouncer was available to run the application against**; the
behaviours above are verified at the connection level, not through a real pooler):

```
[databases]
; one wildcard entry: every tenant database and the master are reached through the pooler
* = host=127.0.0.1 port=5432

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 5             ; server connections per (database, user) pair
max_db_connections = 20           ; per database
max_user_connections = 20
reserve_pool_size = 2
server_idle_timeout = 300
query_wait_timeout = 30
ignore_startup_parameters = extra_float_digits
auth_type = scram-sha-256
auth_user = pgbouncer_auth        ; a login allowed to read pg_shadow through a SECURITY DEFINER function
auth_query = SELECT usename, passwd FROM pgbouncer.user_lookup($1)
```

Each business has **its own database login created at provisioning**, so a static `userlist.txt` cannot work: use
`auth_query` as above. PgBouncer keeps a pool per (database, login), which is why `max_db_connections` matters with
many businesses.

**Putting an existing installation behind PgBouncer.** The application connects to each business with a URL stored
(encrypted) in `master.tenant`, built from `ZIIRA_TENANT_SERVER_URL` when the business was created, so it contains
PostgreSQL's host and port. Changing `ZIIRA_TENANT_SERVER_URL` only affects *new* businesses; there is **no command yet
that rewrites the stored URLs of existing ones**. The simple way around that: move PostgreSQL to another port and give
PgBouncer the port PostgreSQL had (`listen_port = 5432`), then set `ZIIRA_PG_TOOL_PORT` to PostgreSQL's new port for
backups and keep the tenant server URL (admin DDL) on the direct port for new businesses.

## Incident and breach response (skeleton)

Fill the names in before you need them. Keep a printed copy.

**Roles**: incident lead (decides, communicates; default: the on-call engineer until the owner takes over), technical
lead (investigates and fixes), communications (customers and regulators; the owner), scribe (keeps the timeline).
**Contacts to hold**: on-call phone numbers, hosting support, the data protection regulator (Kenya: the Office of the
Data Protection Commissioner; elsewhere: the authority of the affected business's country), the legal adviser, the
email and SMS providers, M-Pesa / Safaricom business support, each customer's named contact.

1. **Detect and declare**: an alert, a customer report or a finding. Anyone may declare an incident; write the time and
   what was seen. Open a private channel and a timeline document. Quote request ids.
2. **Contain** (stop it getting worse; preserve evidence first where you can): revoke the exposed credential
   (rotate `ZIIRA_SECRET_KEY` signs everyone out; API keys are revoked in the admin screens; sessions are revoked per
   user or per business); suspend the business (`master.tenant.status = 'suspended'`); block an address at the proxy;
   take the endpoint off. Snapshot the database and keep the logs **before** cleaning up.
3. **Assess**: what data (whose, which fields), how many people, since when, is it still happening, was data
   *accessed*, *changed* or *taken*. The audit log (hash-chained per business: `verify_chain`) and the access logs
   (`request_id`, `tenant_id`, `route`) answer most of it. Ziira's staff access to a tenant's data is only with consent and is logged.
4. **Decide notification** (the owner, with legal advice), **inside the legal deadline**. Ziira is a data processor for
   its customers' data: tell the affected businesses (controllers) **without undue delay** and give them what they need
   to meet their own duty (many laws, including Kenya's Data Protection Act, require notifying the regulator within 72
   hours of becoming aware of a breach likely to harm people, and the affected people without undue delay when there
   is high risk; **confirm the current deadlines and your contract's terms with counsel; this document is not legal advice**).
   For Ziira's own customer data Ziira is the controller and has the regulator duty itself. Start the 72-hour clock
   when you *became aware*, not when you finished investigating; notify in stages if you must.
5. **Eradicate and recover**: fix the cause, rotate every secret that could have been exposed (database passwords of
   the affected logins, provider keys, `ZIIRA_CREDENTIALS_KEY` re-encryption is a manual job: plan it), restore from
   backup if data was changed (situation B/C above), `ziira verify`, watch closely.
6. **Review** within five working days, blameless: timeline, root cause, what detected it, what delayed it, actions
   with owners and dates. Update this document, the alerts and the tests. Keep the record (regulators ask).
7. **Communicate** plainly: what happened, what data, what we have done, what the customer should do, who to call.
   No speculation, no blame.

## On-call checklist

At the start of a shift: you can reach the secrets manager, the server, the dashboards and this document; the phone
works; yesterday's incidents and open follow-ups are read.

Every morning (10 minutes):
- [ ] Backup finished last night (exit code, newest manifest age < 26 h); off-site copy present.
- [ ] WAL archiving healthy (last archived WAL < 15 minutes old); disk usage under 80%.
- [ ] Dashboards: error rate, p95 latency, `ziira_jobs_oldest_due_seconds`, `ziira_outbox_lag_seconds`, `ziira_outbox_stuck`,
      `ziira_jobs_failed`, `ziira_periodic_failing_tenants`, `ziira_notifications_failed`, `ziira_intel_check_failures`.
- [ ] Nightly `ziira verify` output read (any problem line is a real defect in a business's data).
- [ ] Exceptions inbox spikes across businesses; sign-in failure/429 patterns.
- [ ] Certificates and provider balances (SMS credit) fine.

When paged:
1. Acknowledge; open the dashboards; `GET /readyz` and `/healthz` from outside.
2. Find a failing request's `request_id` (error bodies carry it) and search the logs for it: the access line has the
   route and tenant, the error line the cause.
3. API down: restart the container; check the database is reachable and `max_connections` not exhausted
   (`select count(*) from pg_stat_activity`); check the last deploy and roll back if it fits.
4. Queue growing: is `worker` running? Restart it; check `ziira worker --once` output for the failing handler; the
   failing item is in the business's exceptions inbox.
5. Database trouble: connections, locks (`pg_stat_activity` with `wait_event`), disk, replication/archiving.
6. Not sure, or customer data may be exposed: declare an incident (above) and wake the owner.

End of shift: hand over open items in writing.
