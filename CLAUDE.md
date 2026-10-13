# CLAUDE.md · Ziira Core

Read this first in every session, then read `docs/PROGRESS.md`: "Current state" and the
"Start here" checklist say exactly where work stands and what to do next.

**At the end of every session (always, without being asked):**
1. Run `make lint` and `make test`; record the result.
2. Update `docs/PROGRESS.md`: current state, phase table, next steps, session log line.
3. Update this file if commands, rules or conventions changed.
4. Commit everything and push to `origin` (https://github.com/freddysundowner/ziira.git).
   Never commit `.env` or other secrets (they are gitignored).

## What this is

Ziira Core is a modular ERP for Kenyan SMEs (first customers: multi-branch retail and distribution).
It pairs with **Ziira Intelligence**, a layer that checks business data daily and alerts owners on
WhatsApp. Product and technical specifications are in `docs/specs/` (each PDF has a `.txt` copy
with the same name; read the `.txt`, since the PDFs need extra tools to read):

- `Ziira_Core_1.0.pdf`: the 12 modules and 1.0 scope
- `Ziira_Intelligence_1.0.pdf`: what Intelligence does
- `Ziira_Core_1.0_Technical_Specification.pdf`: architecture, engines (ledger, inventory, POS,
  payments, eTIMS, payroll), security, build plan; Appendix A is the full database schema

## Stack (decided)

Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic v2, PostgreSQL 16, Redis (later, for jobs),
React for web and POS (later). Hosting is a VPS (do not document hosting details).
eTIMS integrates directly with KRA systems.

## Commands

```bash
bash scripts/run_local.sh     # one step: venv, master DB + template, demo business, API on :8000
make db-up                    # PostgreSQL 16 in Docker (port from ZIIRA_DB_PORT in .env)
make test                     # all tests (creates/drops ziira_test_master, _template, _t_* databases)
make lint                     # ruff + mypy + import-linter
.venv/bin/ziira units | install --all | uninstall <unit>          # platform (master database)
.venv/bin/ziira tenants | enable <tenant> <unit> | disable ... | remove ...   # <tenant> = code or id
.venv/bin/ziira drop-tenant <code> --confirm <code>                # deletes the tenant's database
.venv/bin/ziira create-tenant NAME --code CODE --company ... --branch-code ... --branch-name ... \
    --owner-name ... --owner-email ...      # owner password from prompt or ZIIRA_OWNER_PASSWORD
.venv/bin/ziira outbox-run [--once]         # deliver events to @subscribe_after handlers
```

On this Mac a Homebrew PostgreSQL 14 uses port 5432, so `.env` points everything at Docker on 5433.
`make test` loads `.env`; running pytest directly needs `set -a; . ./.env; set +a` first.
Demo business: workspace `demo-hardware`, login `owner@demo-hardware.test`, password `demo-pass-123`.
Key settings (`ZIIRA_*`): `MASTER_DATABASE_URL`, `TENANT_SERVER_URL`, `CREDENTIALS_KEY` (encrypts tenant
connection strings; losing it locks out every tenant), `SECRET_KEY` (signs tokens), `ENV`.

## Architecture rules (do not break)

0. **One database per tenant** (decision 0004). The master database (`ziira_master`) lists tenants
   and their encrypted connection strings; business data never goes there. Each tenant database is
   copied from `ziira_template` (kernel only) and gets a unit's tables when the tenant enables it.
   Each tenant has its own login. Code reaches a tenant only through `tenant_session(tenant_id)`.
1. **Kernel + units.** `ziira/kernel` is always on. Modules (`ziira/modules/*`) and plugins
   (`ziira/plugins/*`) are units: installed on the platform, enabled per tenant (tables created in
   that tenant's database), disabled, removed from a tenant, uninstalled.
2. **One PostgreSQL schema per unit** inside each tenant database (`products`, `pos`, ...;
   plugins use `plg_<name>`).
3. **Foreign keys only to the kernel and to units listed in `requires`.** Links to optional units
   are plain UUIDs ("soft references").
4. **Units import only `ziira.sdk`** (never `ziira.kernel`) and other units only via their
   `public.py`. Enforced by `tests/test_architecture.py` and import-linter.
5. **Units communicate by events**: `publish(session, Event(...))` and `@subscribe("type")` in
   `events.py`. Subscribers run inside the publisher's transaction.
6. **Every tenant table** still has `tenant_id` with forced row-level security (second layer). The app
   connects with the tenant's own login (non-owner). Tenant is set per transaction (`app.tenant_id`).
7. **Immutable records:** posted documents are never edited; correct with reversals.
   Stock movements, journal entries/lines and the audit log reject UPDATE/DELETE in the database.
8. **Money is Decimal**, never float (`ziira.sdk.money`).
9. **Every endpoint checks access.** Routes declare `require_permission(...)`; services check scope with
   `current_context().require(perm, company_id=..., branch_id=...)` and filter lists with `companies_with`.
10. **Check ids before saving.** Call `check_company(session, company_id, branch_id)` before saving
   records that name a company or branch, so a wrong id gives a clear error (and foreign keys,
   which ignore row-level security, are never the only check).

## Module layout (copy `ziira/modules/products`)

```
manifest.toml      name, version, requires, optional, permissions, events, api_prefix,
                   [roles] (default role grants), [reason_codes] (seeded per tenant)
migrations/        0001_init.up.sql / .down.sql; new changes = new numbered pair, never edit applied ones
api/               routes.py (HTTP only) + schemas.py
services/          one file per use case: validate (domain) → repository → audit_record → publish
domain/            pure business rules, unit-tested, no DB/HTTP
repository/        models.py + <module>_repo.py, this schema only
events.py          @subscribe handlers
public.py          the only file other units may import
tests/             unit tests for domain rules
```

## Conventions

- Type hints everywhere; clear names (`post_stock_adjustment`, not `proc_adj`); docstrings on public functions.
- Every change ships with tests. Domain rules get unit tests; flows get API/database tests in `tests/`.
- Reason codes required for voids, refunds, discounts above policy, price overrides, stock adjustments.
- Record creator and approver separately; enforce separation of duties where configured.
- Statutory payroll rates live in `people.statutory_rate_table` (effective-dated data), never in code.
- Kernel services for modules (via `ziira.sdk`): `next_document_number`, `check_reason`, `submit_for_approval`
  (+ `@subscribe("approval.decided")`), `@subscribe_after`. See `docs/adding-a-module.md`.
- Auth: sign-in with workspace code + email/phone + password; bearer tokens; API keys (`X-API-Key`).
  Development only: `X-Tenant-ID` (or `ZIIRA_DEV_DEFAULT_TENANT`) acts with every permission; refused in production.
- Permission tests sign in as real users (`tests/conftest.py`: `make_tenant`, `sign_in`), never the dev header.

## Where things are

`docs/PROGRESS.md` (state, checklist, log) · `docs/adding-a-module.md` · `docs/writing-a-plugin.md` ·
`docs/decisions/0001-0004` · `docs/specs/*.txt` · kernel code map in PROGRESS.md "What exists, and where".

## Working style for this project

- The owner builds mostly with AI assistance; keep code simple to follow and well separated.
- Prefer finishing one module end to end (with tests) over partial work across many.
- Run `make test` before saying something works.
