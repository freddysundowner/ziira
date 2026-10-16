-- The M-Pesa plugin keeps no data of its own: accounts, credentials, prompts and transactions are the Payments module's
-- (provider-neutral). The schema exists so the plugin has a place for tables if it ever needs one.
create schema if not exists plg_mpesa;
comment on schema plg_mpesa is 'M-Pesa (Daraja) provider plugin';
