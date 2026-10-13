-- Ziira Core 1.0 · schema 'kernel' · migration 0002 (written by hand)
-- Sign-in by workspace code, user sessions with device-bound refresh tokens,
-- approval amounts per company, and outbox error tracking.

-- Workspace code: what a user types to say which business they sign in to.
alter table kernel.tenant add column code text unique
  check (code ~ '^[a-z0-9][a-z0-9-]{1,39}$');
comment on column kernel.tenant.code is 'Workspace code used at sign-in, e.g. demo-hardware';

create table kernel.user_session (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  user_id uuid not null references kernel.app_user(id),
  channel text not null check (channel in ('web', 'pos', 'api', 'whatsapp')),
  device_id text not null,
  device_name text,
  refresh_hash text not null unique,
  last_used_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz
);
comment on table kernel.user_session is 'A signed-in device. Refresh tokens are stored hashed and bound to the device.';
create index user_session_ix1 on kernel.user_session (tenant_id, user_id) where revoked_at is null;
alter table kernel.user_session enable row level security;
alter table kernel.user_session force row level security;
create policy tenant_isolation on kernel.user_session
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- Approvals: the company and amount decide which rules (steps) apply.
alter table kernel.approval_request add column company_id uuid references kernel.company(id);
alter table kernel.approval_request add column amount numeric(18,2);

-- Outbox: why the last delivery attempt failed.
alter table kernel.event_outbox add column last_error text;
