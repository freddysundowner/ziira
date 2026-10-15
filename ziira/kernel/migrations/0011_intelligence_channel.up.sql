-- Actions Intelligence carries out by itself under an owner's rule (Intelligence level 4) are audited with their own
-- channel, so they can always be told apart from what a person did.
alter table kernel.audit_log drop constraint audit_log_channel_check;
alter table kernel.audit_log add constraint audit_log_channel_check
  check (channel in ('web', 'pos', 'api', 'whatsapp', 'system', 'import', 'support', 'intelligence'));
