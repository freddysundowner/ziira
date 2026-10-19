-- Invoices made for another unit's work (time billed, a job, a membership period) remember where they came from, so asking
-- again for the same source returns the same invoice instead of a second one. Lines may carry their own wording.
alter table pos.sales_invoice add column source_type text;
alter table pos.sales_invoice add column source_id uuid;
comment on column pos.sales_invoice.source_type is 'Which unit/record asked for this invoice (e.g. timebilling.invoice_batch)';
create unique index sales_invoice_one_per_source on pos.sales_invoice (source_type, source_id)
  where source_type is not null and status <> 'cancelled';
alter table pos.sales_invoice_line add column description text;
