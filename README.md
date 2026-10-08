# Ziira Core

Modular ERP for Kenyan businesses, built as a small **kernel** with **pluggable modules** and **plugins**.
Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL 16.

> **Status: foundation (build plan phase 1).** The kernel, module and plugin system, all 110 database
> tables and the Products module work and are tested. The other modules have their manifests,
> migrations and folders in place, and are built next using Products as the template.

## What works today

| Part | State |
|---|---|
| Kernel: tenancy, row-level security, sessions, events and outbox, audit hash chain | Working, tested |
| Module and plugin registry: install, enable, disable, uninstall with dependency rules | Working, tested |
| CLI (`ziira ...`) | Working |
| Database: 11 schemas, 110 tables, migrations per unit | Working, tested |
| Products module (API, services, domain rules, repository) | Working, tested |
| Example plugin `catalog_stats` (own schema, event subscriber, API) | Working, tested |
| Inventory, POS, Payments, CRM, Purchasing, Finance, People, Command Center | Tables, manifests and folders only |
| Authentication | Not yet: development uses the `X-Tenant-ID` header |

## Run it in one step (Mac)

```bash
cd ~/projects/ziira-core
bash scripts/run_local.sh
```

The script finds Python 3.12+, starts PostgreSQL (Docker Desktop if it is running, otherwise a
PostgreSQL installed on the Mac), installs all tables, creates a demo tenant with sample products,
and starts the API. Open **http://localhost:8000/docs**. In development, requests without an
`X-Tenant-ID` header use the demo tenant, so you can try endpoints straight from that page.

## Quick start, step by step (Mac)

You need Python 3.12+ and either Docker Desktop or a local PostgreSQL 16.

```bash
cd ziira-core
make setup          # virtual environment + dependencies, creates .env
make db-up          # PostgreSQL + Redis in Docker
make install        # creates all schemas and tables
make test           # 27 tests against a throwaway ziira_test database
```

Without Docker (Homebrew `postgresql@16` or Postgres.app), run once as a superuser:

```bash
psql -d postgres -f scripts/setup_local_db.sql
```

then `make install` and `make test` as above.

### Create a tenant and try the API

```bash
.venv/bin/ziira create-tenant "Pevma" --company "Pevma Hardware" --branch-code THK --branch-name Thika
# prints tenant_id, company_id, branch_id

.venv/bin/ziira enable <tenant_id> products
make run            # API on http://localhost:8000, interactive docs at /docs
```

Every request sends `X-Tenant-ID: <tenant_id>`. In the docs page, set it on each call.

```bash
curl -X POST localhost:8000/api/v1/products/uoms -H "X-Tenant-ID: <tenant_id>" \
     -H "Content-Type: application/json" -d '{"code":"BAG","name":"Bag"}'
```

## Commands

| Command | Does |
|---|---|
| `ziira units` | List units and whether they are installed |
| `ziira install <unit>` / `--all` | Install units (and the units they require) |
| `ziira uninstall <unit>` | Remove a unit's schema; refused if anything depends on it |
| `ziira create-tenant NAME --company ... --branch-code ... --branch-name ...` | New tenant with a company and branch |
| `ziira enable <tenant> <unit>` | Enable for a tenant (enables required units too) |
| `ziira disable <tenant> <unit>` | Disable for a tenant; data is kept |

## Layout

```
ziira/
  kernel/        tenancy, database, registry, events, audit, app, CLI   (modules never import this)
  sdk/           the only kernel interface modules and plugins may use
  modules/       one folder per module: manifest.toml, migrations/, api/, services/,
                 domain/, repository/, events.py, public.py, tests/
  plugins/       one folder per plugin, same layout, own schema plg_<name>
tests/           kernel, lifecycle, database-rule, API and architecture tests
docs/            how to add a module or plugin, decisions, specifications
```

## Rules that keep it modular

1. A unit's tables live in its own PostgreSQL schema.
2. Foreign keys point only to the kernel and to required units. Optional links are plain IDs.
3. Units import the kernel only through `ziira.sdk`, and other units only through their `public.py`.
   `tests/test_architecture.py` fails the build if this is broken.
4. Units talk to each other through events (`publish` / `@subscribe`), not by calling internals.
5. Every unit declares itself in `manifest.toml`: version, requires, optional, permissions, events, API prefix.

See `docs/adding-a-module.md` and `docs/writing-a-plugin.md`.

## Database rules enforced by PostgreSQL

- Row-level security on every tenant table; the app role cannot see or write other tenants' rows.
- Stock movements, journal entries and lines, and the audit log cannot be updated or deleted.
- Unbalanced journal entries are rejected at commit.
- Stock adjustments, write-offs and voided sales require a reason code.

## Specifications

`docs/specs/` holds the Ziira Core 1.0 product document, the Ziira Intelligence document and the
technical specification (with the full database schema in Appendix A).
