-- Password-only operator sign-in (ZIIRA_OPERATOR_MFA=off): a temporary password must be changed at the next sign-in,
-- sessions get an idle limit, and the operator trail also records sign-ins that name nobody (a wrong email).

alter table master.operator add column must_change_password boolean not null default false;
alter table master.operator add column password_changed_at timestamptz;
comment on column master.operator.must_change_password is 'True after a reset or a console-made account: the only thing the operator may do is change the password.';

alter table master.operator_session add column last_seen_at timestamptz not null default now();
comment on column master.operator_session.last_seen_at is 'The last request of this sign-in; with ZIIRA_OPERATOR_MFA=off a sign-in idle longer than ZIIRA_OPERATOR_IDLE_MINUTES ends.';

alter table master.operator_action_log alter column operator_id drop not null;
