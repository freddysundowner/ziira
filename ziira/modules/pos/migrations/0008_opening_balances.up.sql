-- Opening balances: what a customer owed when the business moved onto Ziira. An *opening invoice* is an invoice with no
-- lines, no tax and no stock, carrying the original invoice's date, due date and reference so ageing works; a customer in
-- credit at go-live is an opening receipt (method 'opening') with the whole amount unallocated.

alter table pos.sales_invoice drop constraint sales_invoice_kind_check;
alter table pos.sales_invoice add constraint sales_invoice_kind_check
  check (kind in ('invoice', 'credit_sale', 'opening_balance'));
alter table pos.sales_invoice add column external_ref text;
comment on column pos.sales_invoice.external_ref is 'Opening invoices: the number the invoice had in the old system';

-- One opening invoice per customer and reference (so importing the same file again changes nothing)
create unique index sales_invoice_one_opening_per_ref on pos.sales_invoice (customer_id, external_ref)
  where kind = 'opening_balance' and status <> 'cancelled';
-- One opening receipt (customer credit) per customer and reference
create unique index customer_receipt_one_opening_per_ref on pos.customer_receipt (customer_id, reference)
  where method = 'opening' and status = 'posted';
