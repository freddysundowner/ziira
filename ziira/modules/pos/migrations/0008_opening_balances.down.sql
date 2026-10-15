drop index if exists pos.customer_receipt_one_opening_per_ref;
drop index if exists pos.sales_invoice_one_opening_per_ref;
alter table pos.sales_invoice disable trigger user;
update pos.sales_invoice set kind = 'invoice' where kind = 'opening_balance';
alter table pos.sales_invoice enable trigger user;
alter table pos.sales_invoice drop column external_ref;
alter table pos.sales_invoice drop constraint sales_invoice_kind_check;
alter table pos.sales_invoice add constraint sales_invoice_kind_check check (kind in ('invoice', 'credit_sale'));
