# 0002 · Tenant isolation with row-level security

**Status:** accepted · October 2026 · the shared database is replaced by one database per tenant (0004); row-level security stays inside each tenant database

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
