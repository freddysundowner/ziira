drop trigger if exists purchase_return_line_protected on purchasing.purchase_return_line;
drop function if exists purchasing.protect_return_line();
drop table if exists purchasing.supplier_credit_note_line;
drop table if exists purchasing.supplier_credit_note;
drop table if exists purchasing.purchase_return_line;
drop table if exists purchasing.purchase_return;
alter table purchasing.supplier_bill_line drop column if exists landed_receipt_id;
drop index if exists purchasing.supplier_bill_one_per_invoice;
create unique index supplier_bill_one_per_invoice on purchasing.supplier_bill (supplier_id, supplier_invoice_no)
  where status <> 'cancelled';
alter table purchasing.supplier_bill drop column if exists posted_figures;
alter table purchasing.supplier_bill drop column if exists reverse_reason;
alter table purchasing.supplier_bill drop column if exists reversed_by;
alter table purchasing.supplier_bill drop column if exists reversed_at;
alter table purchasing.supplier_bill drop column if exists credited;
alter table purchasing.supplier_bill drop constraint supplier_bill_status_check;
alter table purchasing.supplier_bill add constraint supplier_bill_status_check
  check (status in ('draft', 'pending_approval', 'posted', 'part_paid', 'paid', 'cancelled'));
