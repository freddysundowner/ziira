alter table pos.sales_invoice_line drop column if exists description;
drop index if exists pos.sales_invoice_one_per_source;
alter table pos.sales_invoice drop column if exists source_id;
alter table pos.sales_invoice drop column if exists source_type;
