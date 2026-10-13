# Ziira Core

Modular ERP for Kenyan businesses, built as a small **kernel** with **pluggable modules** and **plugins**.
Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL 16.

**Every business has its own database.** A master database lists the businesses (tenants) and
holds each one's connection, encrypted. New tenant databases are copied from a template in about
a second. See `docs/decisions/0004-database-per-tenant.md`.

```
ziira_master                 tenants, encrypted connection strings, units offered
ziira_template               kernel only; copied for each new tenant
ziira_t_pevma                Pevma's own database: kernel + the modules Pevma enabled
ziira_t_mamamboga            another business, its own database and login
```

> **Status: build plan phases 1 (foundation), 2 (catalogue and inventory), 3 (ledger) and 4 (POS and payments) complete; phase 5 (eTIMS) is next.** The kernel
> (database per tenant, sign-in, roles and scopes, audit, numbering, reason codes, approvals, events
> and outbox, retry-safe requests, background jobs, the exceptions inbox), the module and plugin system and the Products,
> Inventory, Finance, Payments and POS modules work and are tested (the Daraja/M-Pesa calls still need their sandbox run). The other
> modules have their manifests, migrations and folders in place, and are built next using Products
> as the template. Where work stands and what comes next: `docs/PROGRESS.md`.

## What works today

| Part | State |
|---|---|
| Database per tenant: master database, template, provisioning, per-tenant logins | Working, tested |
| Kernel: row-level security (second layer), events and outbox processor, audit hash chain | Working, tested |
| Sign-in (workspace code + email/phone + password), device-bound refresh tokens, API keys | Working, tested |
| Users, roles and scopes (tenant, company, branch, own); permission checks on every endpoint | Working, tested |
| Document numbering, reason codes, approval matrix with separation of duties | Working, tested |
| Module and plugin registry: install, enable (creates tables in the tenant's database), disable, remove, uninstall | Working, tested |
| CLI (`ziira ...`) | Working |
| Schema: 110 tables in 11 schemas, created per tenant database as units are enabled | Working, tested |
| Products module (API, services, domain rules, repository) | Working, tested |
| Example plugin `catalog_stats` (own schema, event subscriber, API, plugs into Products' hook and extension point) | Working, tested |
| Extension points and validation hooks between units | Working, tested |
| Web app (`frontend/`): sign-in, module shell, Products, Users and Roles, plugin slots; English and Swahili | Working, tested |
| Inventory: stock ledger, weighted average costing, locations, opening stock, adjustments, transfers, counts, nightly check | Working, tested (no web screens yet) |
| Finance: chart of accounts, posting engine, periods, manual journals with approval, trial balance, general ledger, books check | Working, tested (no web screens yet) |
| POS, Payments, CRM, Purchasing, People, Command Center, Intelligence | Tables, manifests and folders only |
| MFA and one-time codes | Not yet (phase 11, needs an SMS/email gateway) |

## Run it in one step (Mac)

```bash
cd ~/projects/ziira-core
bash scripts/run_local.sh
```

The script finds Python 3.12+, starts PostgreSQL (Docker Desktop if it is running, otherwise a
PostgreSQL installed on the Mac), sets up the master database and template, creates a demo
business in its own database with sample products, and starts the API.
Open **http://localhost:8000/docs**. In development, requests without credentials
act as the demo tenant with every permission, so you can try endpoints straight from that page.
To sign in for real: workspace `demo-hardware`, login `owner@demo-hardware.test`, password `demo-pass-123`.

If another PostgreSQL already uses port 5432, set `ZIIRA_DB_PORT=5433` in `.env` (and use 5433 in the
database URLs there); Docker then publishes the database on that port.

## Quick start, step by step (Mac)

You need Python 3.12+ and either Docker Desktop or a local PostgreSQL 16.

```bash
cd ziira-core
make setup          # virtual environment + dependencies, creates .env
make db-up          # PostgreSQL + Redis in Docker
make install        # master database, tenant template, units offered
make lint           # ruff, mypy, import-linter
make test           # all tests (throwaway ziira_test_* databases)
```

Without Docker (Homebrew `postgresql@16` or Postgres.app), run once as a superuser:

```bash
psql -d postgres -f scripts/setup_local_db.sql
```

then `make install` and `make test` as above.

### Create a tenant and try the API

```bash
.venv/bin/ziira create-tenant "Pevma" --code pevma --company "Pevma Hardware" --branch-code THK \
    --branch-name Thika --owner-name "Jane Wanjiru" --owner-email jane@pevma.co.ke
# asks for the owner's password; prints tenant_id, company_id, branch_id, owner_id

.venv/bin/ziira enable pevma products     # creates the Products tables in Pevma's database
make run            # API on http://localhost:8000, interactive docs at /docs
```

Sign in, then send the access token on every request:

```bash
curl -X POST localhost:8000/api/v1/auth/sign-in -H "Content-Type: application/json" \
     -d '{"workspace":"pevma","login":"jane@pevma.co.ke","password":"<password>","device_id":"my-laptop"}'
# returns access_token (15 minutes) and refresh_token (use /api/v1/auth/refresh before it expires)

curl -X POST localhost:8000/api/v1/products/uoms -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" -d '{"code":"BAG","name":"Bag"}'
```

The owner then creates users (`POST /api/v1/users`) and gives them roles over the whole business,
a company or a branch (`POST /api/v1/users/{id}/roles`). Integrations use API keys
(`POST /api/v1/api-keys`, header `X-API-Key`).

In development only, `X-Tenant-ID: <tenant_id>` acts as that tenant with every permission.
Set `ZIIRA_ENV=production` to refuse that header and the development secret key.

## Commands

| Command | Does |
|---|---|
| `ziira units` | List units and whether the platform offers them |
| `ziira install <unit>` / `--all` | Offer units (and what they require); also upgrades every tenant database that has them |
| `ziira uninstall <unit>` | Stop offering a unit; refused while any tenant database has it |
| `ziira create-tenant NAME --code ... --company ... --branch-code ... --branch-name ... --owner-name ... --owner-email ...` | New tenant with a company, branch, default roles and its owner |
| `ziira tenants` | List tenants and their databases |
| `ziira enable <tenant> <unit>` | Enable for a tenant (creates its tables there; enables required units too) |
| `ziira disable <tenant> <unit>` | Disable for a tenant; data is kept |
| `ziira remove <tenant> <unit>` | Drop a disabled unit's tables from that tenant's database |
| `ziira drop-tenant <code> --confirm <code>` | Delete a tenant's database, login and record (cannot be undone) |
| `ziira outbox-run [--once]` | Deliver committed events to after-commit subscribers |
| `ziira worker [--once]` | Run the outbox and background jobs (M-Pesa prompts, matching) and purge old keys and jobs |
| `ziira verify [tenant] [--unit U] [--fix]` | Run units' integrity checks (exit 1 while problems remain); `ziira stock-verify` checks the stock ledger |

## Layout

```
ziira/
  kernel/        tenants (database per tenant), auth, users and roles, registry, events, outbox,
                 audit, numbering, reason codes, approvals, app, CLI   (modules never import this)
    master_migrations/   schema of the master database
    migrations/          kernel schema, applied to the template and every tenant database
  sdk/           the only kernel interface modules and plugins may use
  modules/       one folder per module: manifest.toml, migrations/, api/, services/,
                 domain/, repository/, events.py, public.py, tests/
  plugins/       one folder per plugin, same layout, own schema plg_<name>
tests/           kernel, auth, permission, lifecycle, database-rule, API and architecture tests
docs/            how to add a module or plugin, decisions, specifications
```

## Rules that keep it modular

1. A unit's tables live in its own PostgreSQL schema, inside each tenant database that enabled it.
2. Foreign keys point only to the kernel and to required units. Optional links are plain IDs.
3. Units import the kernel only through `ziira.sdk`, and other units only through their `public.py`.
   `tests/test_architecture.py` fails the build if this is broken.
4. Units talk to each other through events (`publish` / `@subscribe`), not by calling internals.
5. Every unit declares itself in `manifest.toml`: version, requires, optional, permissions, default role
   grants, reason codes, events, API prefix.

See `docs/adding-a-module.md` and `docs/writing-a-plugin.md`.

## Database rules enforced by PostgreSQL

- Each tenant's login can connect only to its own database.
- Inside a tenant database, row-level security still applies to every table (a second layer), and the
  tenant's login does not own the tables.
- Stock movements, journal entries and lines, and the audit log cannot be updated or deleted.
- Unbalanced journal entries are rejected at commit.
- Stock adjustments, write-offs and voided sales require a reason code.

## Documentation

| Document | Read it for |
|---|---|
| `docs/PROGRESS.md` | Where work stands, the next steps (checklist), deferred items, session log |
| `CLAUDE.md` | Rules and commands for anyone (or any AI session) changing the code |
| `docs/adding-a-module.md` | Building a module: layout, permissions, scope, numbering, reasons, approvals |
| `docs/writing-a-plugin.md` | Building a plugin |
| `docs/extending-units.md` | Validation hooks and extension points between units |
| `docs/frontend.md` | The web app: modules, slots, commands |
| `docs/decisions/` | Why things are built this way (0001 units · 0002 row-level security · 0003 auth · 0004 database per tenant) |
| `docs/specs/` | Product, Intelligence and technical specifications, as PDF and plain text (Appendix A: full schema) |
| `ziira/modules/*/README.md` | Each module's tables, events, permissions and status |
