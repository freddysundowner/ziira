-- Multi-factor sign-in (time-based one-time codes) and the business's policy on who must use it.
-- The secret is stored encrypted; a code can be used once (last_counter); backup codes are stored as hashes.

alter table kernel.tenant add column mfa_policy text not null default 'off'
  check (mfa_policy in ('off', 'privileged', 'everyone'));
comment on column kernel.tenant.mfa_policy is 'Who must sign in with a second factor: nobody, people with powerful roles, or everyone';

create table kernel.user_mfa (
  user_id uuid primary key references kernel.app_user(id),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  secret_enc text not null,
  confirmed_at timestamptz,
  last_counter bigint not null default 0,
  backup_hashes jsonb not null default '[]'
);
comment on table kernel.user_mfa is 'A user''s authenticator-app secret (encrypted) and unused backup codes (hashed).';
alter table kernel.user_mfa enable row level security;
alter table kernel.user_mfa force row level security;
create policy tenant_isolation on kernel.user_mfa
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
