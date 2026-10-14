alter table kernel.integration_credential drop constraint if exists integration_credential_provider_check;
alter table kernel.company alter column base_currency set default 'KES';
alter table kernel.company rename column tax_id to kra_pin;
