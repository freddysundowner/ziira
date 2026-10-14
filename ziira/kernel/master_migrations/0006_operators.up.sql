-- Platform staff ("operators") are not users of any business. They sign in to the platform with a password and a
-- compulsory second factor, and open a support session in a business only while that business has an active grant.
-- Every start, end and request of a support session is kept in support_access_log.

create table master.operator (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  password_hash text not null,
  status text not null default 'active' check (status in ('active', 'disabled')),
  mfa_secret_enc text not null,
  mfa_last_counter bigint not null default 0,
  created_at timestamptz not null default now(),
  last_sign_in_at timestamptz
);
create unique index operator_email_ix on master.operator (lower(email));
comment on table master.operator is 'Ziira staff who may open support sessions. Created only from the command line.';

create table master.operator_session (
  id uuid primary key default gen_random_uuid(),
  operator_id uuid not null references master.operator(id) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  ip_address text
);
create index operator_session_ix on master.operator_session (operator_id);

create table master.support_access_log (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  event text not null check (event in ('start', 'end', 'revoked', 'request', 'refused')),
  operator_id uuid not null,
  operator_name text not null,
  tenant_id uuid not null,
  grant_id uuid,
  support_session_id uuid,
  method text,
  route text,
  status int,
  detail jsonb
);
create index support_access_log_ix1 on master.support_access_log (tenant_id, occurred_at);
create index support_access_log_ix2 on master.support_access_log (operator_id, occurred_at);
create index support_access_log_ix3 on master.support_access_log (support_session_id);
comment on table master.support_access_log is 'Every start/end of a support session and every request made in one: who, which business, which grant, route template and status. Never deleted by the application.';
create or replace function master.forbid_support_log_change() returns trigger language plpgsql as $$
begin
  raise exception 'The support access log cannot be changed' using errcode = '23000';
end $$;
create trigger support_access_log_immutable before update or delete on master.support_access_log
  for each row execute function master.forbid_support_log_change();
