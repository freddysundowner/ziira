-- Payments knows no provider: a provider plugin names its own sources, and an account with no integration is 'manual'.
-- The old values stay valid (rows are not touched).
alter table payments.external_transaction drop constraint external_transaction_source_check;
alter table payments.external_transaction add constraint external_transaction_source_check
  check (source ~ '^[a-z][a-z0-9_]{2,39}$');
alter table payments.payment_account alter column provider set default 'manual';
