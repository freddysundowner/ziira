-- Ziira Core 1.0 · master database · migration 0001 (written by hand)
-- The control plane: which tenants exist, how to reach each tenant's own database,
-- and which units the platform offers. Business data never lives here.

create schema if not exists master;

create table master.tenant (
  id uuid primary key,
  code text not null unique check (code ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  name text not null,
  status text not null default 'provisioning'
    check (status in ('provisioning', 'active', 'suspended', 'closed')),
  db_name text not null unique,
  app_role text not null unique,
  -- Full connection strings, encrypted with ZIIRA_CREDENTIALS_KEY:
  -- the tenant's own login (row-level security applies) and an owner login for migrations.
  app_url_encrypted text not null,
  admin_url_encrypted text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
comment on table master.tenant is 'A customer business and the connection to its own database.';

create table master.unit (
  name text primary key,
  kind text not null check (kind in ('module', 'plugin')),
  version text not null,
  manifest jsonb not null,
  installed_at timestamptz not null default now()
);
comment on table master.unit is 'Units the platform offers. Each tenant database installs the ones it enables.';
