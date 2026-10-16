alter table kernel.audit_log drop constraint audit_log_channel_check;
alter table kernel.audit_log add constraint audit_log_channel_check
  check (channel in ('web', 'pos', 'api', 'whatsapp', 'system', 'import', 'support', 'intelligence'));
