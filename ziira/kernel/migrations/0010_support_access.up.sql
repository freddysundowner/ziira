-- Support access: a business lets Ziira staff look at (or work in) its data for a limited time, with a reason, and can
-- take that back at any moment. Staff are not users of the business: a support session has no user, only the grant it
-- runs under. Every request in a session is also written to the audit log (channel 'support').

create table kernel.support_grant (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  reason text not null check (length(btrim(reason)) > 0),
  level text not null check (level in ('read', 'full')),
  note text,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  revoked_by uuid references kernel.app_user(id)
);
comment on table kernel.support_grant is 'Permission a business gave to Ziira staff to access its data: reason, read-only or full, until when.';
create index support_grant_ix1 on kernel.support_grant (tenant_id, expires_at);
alter table kernel.support_grant enable row level security;
alter table kernel.support_grant force row level security;
create policy tenant_isolation on kernel.support_grant
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.support_session (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  grant_id uuid not null references kernel.support_grant(id),
  operator_id uuid not null,
  operator_name text not null,
  level text not null check (level in ('read', 'full')),
  started_at timestamptz not null default now(),
  expires_at timestamptz not null,
  ended_at timestamptz
);
comment on table kernel.support_session is 'One time a staff member opened the business under a grant. operator_id points into the master database (soft reference).';
create index support_session_ix1 on kernel.support_session (tenant_id, grant_id);
alter table kernel.support_session enable row level security;
alter table kernel.support_session force row level security;
create policy tenant_isolation on kernel.support_session
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

alter table kernel.audit_log drop constraint audit_log_channel_check;
alter table kernel.audit_log add constraint audit_log_channel_check
  check (channel in ('web', 'pos', 'api', 'whatsapp', 'system', 'import', 'support'));
