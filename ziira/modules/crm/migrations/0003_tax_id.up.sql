-- A customer's tax number is just that: no country's format is assumed.
alter table crm.customer rename column kra_pin to tax_id;
