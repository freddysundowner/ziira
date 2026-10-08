# CLAUDE.md · Ziira Core

Read this first in every session, then read `docs/PROGRESS.md` to see where work stands.
At the end of every session, update `docs/PROGRESS.md` (status, next step, session log).

## What this is

Ziira Core is a modular ERP for Kenyan SMEs (first customers: multi-branch retail and distribution).
It pairs with **Ziira Intelligence**, a layer that checks business data daily and alerts owners on
WhatsApp. Product and technical specifications are in `docs/specs/`:

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
bash scripts/run_local.sh     # one step: venv, database, tables, demo data, API on :8000
make test                     # all tests (creates/drops database ziira_test)
make lint                     # ruff + import-linter
.venv/bin/ziira units | install --all | enable <tenant> <unit> | disable ... | uninstall <unit>
```

## Architecture rules (do not break)

1. **Kernel + units.** `ziira/kernel` is always on. Modules (`ziira/modules/*`) and plugins
   (`ziira/plugins/*`) are units: installed, enabled per tenant, disabled, uninstalled.
2. **One PostgreSQL schema per unit** (`products`, `pos`, ...; plugins use `plg_<name>`).
3. **Foreign keys only to the kernel and to units listed in `requires`.** Links to optional units
   are plain UUIDs ("soft references").
4. **Units import only `ziira.sdk`** (never `ziira.kernel`) and other units only via their
   `public.py`. Enforced by `tests/test_architecture.py` and import-linter.
5. **Units communicate by events**: `publish(session, Event(...))` and `@subscribe("type")` in
   `events.py`. Subscribers run inside the publisher's transaction.
6. **Every tenant table** has `tenant_id` with forced row-level security. The app connects as
   `ziira_app` (non-owner). Tenant is set per transaction (`app.tenant_id`).
7. **Immutable records:** posted documents are never edited; correct with reversals.
   Stock movements, journal entries/lines and the audit log reject UPDATE/DELETE in the database.
8. **Money is Decimal**, never float (`ziira.sdk.money`).

## Module layout (copy `ziira/modules/products`)

```
manifest.toml      name, version, requires, optional, permissions, events, api_prefix
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
- Development auth: tenant from `X-Tenant-ID` header or `ZIIRA_DEV_DEFAULT_TENANT`. Real auth is a later phase.

## Working style for this project

- The owner builds mostly with AI assistance; keep code simple to follow and well separated.
- Prefer finishing one module end to end (with tests) over partial work across many.
- Run `make test` before saying something works.
