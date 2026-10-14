alter table kernel.audit_log drop constraint if exists audit_log_channel_check;
alter table kernel.audit_log add constraint audit_log_channel_check
  check (channel in ('web', 'pos', 'api', 'whatsapp', 'system', 'import')) not valid;
drop table if exists kernel.support_session;
drop table if exists kernel.support_grant;
