-- Operator console: how recently an operator's sign-in was confirmed with a second-factor code (changes ask again when
-- it is older than ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES), and the platform's own trail of what operators change.

alter table master.operator_session add column mfa_verified_at timestamptz;
update master.operator_session set mfa_verified_at = created_at;
alter table master.operator_session alter column mfa_verified_at set default now();

create table master.operator_action_log (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  operator_id uuid not null,
  operator_name text not null,
  action text not null,
  target text,
  outcome text not null default 'ok' check (outcome in ('ok', 'refused', 'failed')),
  reason text,
  detail jsonb,
  ip_address text
);
create index operator_action_log_ix1 on master.operator_action_log (occurred_at);
create index operator_action_log_ix2 on master.operator_action_log (operator_id, occurred_at);
comment on table master.operator_action_log is 'Every change an operator makes in the console (installing units, switching a business''s units, upgrades), with the reason where one is required. Never deleted by the application.';
create or replace function master.forbid_operator_log_change() returns trigger language plpgsql as $$
begin
  raise exception 'The operator action log cannot be changed' using errcode = '23000';
end $$;
create trigger operator_action_log_immutable before update or delete on master.operator_action_log
  for each row execute function master.forbid_operator_log_change();
