# 0002 · Tenant isolation with row-level security

**Status:** accepted · October 2026 · partly replaced by 0004 (see Update below)

## Decision

All tenants share one database. Every tenant table has `tenant_id` and a forced row-level security
policy comparing it with `app.tenant_id`, which the kernel sets at the start of every transaction.
The application connects as `ziira_app`, a role that does not own the tables.

## Why

A missing `WHERE tenant_id = ...` in application code cannot leak data, because PostgreSQL itself
hides and blocks other tenants' rows.

## Consequences

- Admin and migration work uses the owner connection; code running there filters tenants explicitly.
- Tests check that a second tenant can neither read nor write the first tenant's rows.

## Update (2026-10-13, decision 0004)

Tenants no longer share one database: each has its own database and login, listed in a master
database. Row-level security stays inside every tenant database as a second layer. The app now
connects with the tenant's own login (not `ziira_app`), which still does not own the tables.
