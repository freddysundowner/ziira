# 0004 · One database per tenant, with a master database

**Status:** accepted · October 2026 · replaces the shared-database part of 0002

## Decision

- Every business (tenant) gets **its own PostgreSQL database** (`ziira_t_<workspace code>`) and
  **its own login** (`zt_<workspace code>`). A login can connect only to its own database
  (`revoke all on database ... from public`).
- A **master database** (`ziira_master`, schema `master`) is the control plane: the list of
  tenants, their status, their database name, and **two full connection strings per tenant**
  (the tenant's own login, and an owner login for migrations), **encrypted** with
  `ZIIRA_CREDENTIALS_KEY`. It also lists the units the platform offers. No business data lives there.
- New tenant databases are **copied from a template** (`ziira_template`) that holds the
  migrated kernel only. Copying takes about a second.
- A tenant database holds the **kernel plus the units that tenant has enabled**. Enabling a unit
  runs its migrations in that tenant's database; `ziira remove` drops them again.
- **Upgrades:** `ziira install <unit>` (or `--all`) applies new migrations to the template and to
  every tenant database that has the unit.
- **Second layer kept:** inside each tenant database every table still has `tenant_id` and forced
  row-level security, and the tenant's login does not own the tables.
- Because each tenant has a full connection string, a tenant can be **moved to another server**
  by copying its database and updating its record in the master database.

## Why

The owner chose the strongest isolation: a business's data is never in the same tables, or even
the same database, as another's. It also gives per-business backup, restore, export and deletion
(useful for the Kenya Data Protection Act), and lets a large tenant move to its own server.

This departs from the specification (section 04 describes one shared database with row-level
security); the specification's "move large tenants to a dedicated database" becomes the default.

## Consequences

- Connection pools are per tenant (small: 2 + 8 overflow). With many tenants, add PgBouncer.
- Platform-wide work (outbox processor, upgrades, later Intelligence baselines) loops over tenants
  listed in the master database.
- Backups, monitoring and migrations run per tenant database; operations must automate this.
- The server login in `ZIIRA_TENANT_SERVER_URL` must be allowed to create databases and roles.
- Losing `ZIIRA_CREDENTIALS_KEY` makes stored connection strings unreadable: keep it in the
  secrets manager and back it up.
- Foreign keys can no longer point at another tenant's rows at all (they are in another database);
  `check_company` is still required, because a missing company id must give a clear error.
