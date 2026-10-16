-- A reminder can go by any channel the business has (a plugin may offer one), so the table no longer lists them.
alter table pos.invoice_reminder drop constraint if exists invoice_reminder_channel_check;
alter table pos.invoice_reminder add constraint invoice_reminder_channel_check
  check (channel ~ '^[a-z][a-z0-9_]{1,39}$');
