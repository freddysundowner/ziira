-- Channels are no longer a fixed list: each messaging provider declares the channel it offers, and a business has only the
-- channels whose provider is enabled for it. So the database stops naming them. Names are still checked by the code
-- (against the providers enabled for the business), and kept short and plain here.
alter table kernel.integration_credential drop constraint if exists integration_credential_provider_check;
alter table kernel.integration_credential add constraint integration_credential_provider_check
  check (provider ~ '^[a-z][a-z0-9_]{1,39}$');
alter table kernel.notification drop constraint if exists notification_channel_check;
alter table kernel.notification add constraint notification_channel_check
  check (channel ~ '^[a-z][a-z0-9_]{1,39}$');
alter table kernel.message_template drop constraint if exists message_template_channel_check;
alter table kernel.message_template add constraint message_template_channel_check
  check (channel ~ '^[a-z][a-z0-9_]{1,39}$');
-- A person's command by chat is audited with the channel 'chat' (the provider's own channel name is in the entry).
alter table kernel.audit_log drop constraint audit_log_channel_check;
alter table kernel.audit_log add constraint audit_log_channel_check
  check (channel in ('web', 'pos', 'api', 'whatsapp', 'system', 'import', 'support', 'intelligence', 'chat'));
