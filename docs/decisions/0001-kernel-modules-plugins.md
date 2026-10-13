# 0001 · Kernel, pluggable modules and plugins

**Status:** accepted · October 2026 · updated by 0004 (one database per tenant)

## Decision

Ziira Core is one Python application made of a kernel plus units (modules and plugins) that can be
installed, enabled per tenant, disabled and uninstalled. Each unit owns one PostgreSQL schema,
declares itself in `manifest.toml`, and talks to other units through events and `public.py`.

## Why

- Businesses need different parts of the ERP; modules must plug in and out without code changes.
- One backend, and one database per tenant, keep a business's sales, stock, payments and ledger in one
  transaction.
- Schemas per unit make uninstalling clean: dropping a schema touches nothing else, because foreign
  keys go only to the kernel and required units.

## Consequences

- Cross-module links to optional modules are not enforced by the database; services must check them.
- Migrations are plain SQL per unit, applied in each tenant database that has the unit and tracked
  in that database's `kernel.schema_migration`. (The specification names Alembic; still an open decision.)
