drop table if exists kernel.user_mfa;
alter table kernel.tenant drop column if exists mfa_policy;
