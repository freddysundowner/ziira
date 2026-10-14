-- Localisation: nothing in the platform assumes a country. A company's tax number is just its tax number, its currency
-- is chosen when it is created, and integrations are named by whoever provides them.

alter table kernel.company rename column kra_pin to tax_id;
alter table kernel.company alter column base_currency drop default;
comment on column kernel.company.tax_id is 'The business''s tax registration number';

-- The eTIMS tables belonged to a plugin that is parked; when it is built it keeps its own tables (plg_<name>).
drop table if exists kernel.etims_submission;
drop table if exists kernel.etims_device;

-- Integration credentials: any provider name (a plugin's own), not a fixed list.
alter table kernel.integration_credential drop constraint if exists integration_credential_provider_check;
alter table kernel.integration_credential add constraint integration_credential_provider_check
  check (provider ~ '^[a-z][a-z0-9_]{1,39}$');
