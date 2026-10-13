-- Phase 7: supplier bank details that change only after confirmation and approval, landed cost on a receipt,
-- match notes on a bill, and records that cannot be rewritten once posted.

alter table purchasing.supplier_bank_account add column status text not null default 'pending_confirmation'
  check (status in ('pending_confirmation', 'pending_approval', 'active', 'superseded', 'rejected'));
alter table purchasing.supplier_bank_account add column confirmed_at timestamptz;
create unique index supplier_bank_one_active on purchasing.supplier_bank_account (supplier_id) where status = 'active';

alter table purchasing.goods_receipt add column landed_cost numeric(18,2) not null default 0;
alter table purchasing.supplier_bill add column match_notes jsonb not null default '[]';
alter table purchasing.supplier_bill add column posted_at timestamptz;
alter table purchasing.supplier_bill add column submitted_by uuid references kernel.app_user(id);
-- A cancelled bill frees its supplier invoice number (the supplier's number may be entered again on a new bill).
alter table purchasing.supplier_bill drop constraint supplier_bill_supplier_id_supplier_invoice_no_key;
create unique index supplier_bill_one_per_invoice on purchasing.supplier_bill (supplier_id, supplier_invoice_no)
  where status <> 'cancelled';
create index supplier_bill_ix2 on purchasing.supplier_bill (supplier_id, status);
create index goods_receipt_ix1 on purchasing.goods_receipt (order_id);
create index supplier_price_ix2 on purchasing.supplier_price (supplier_id, product_id, effective_date);

-- A posted receipt is what arrived: its lines never change and nothing is deleted.
create trigger goods_receipt_line_immutable before update or delete on purchasing.goods_receipt_line
  for each row execute function kernel.forbid_change();
create function purchasing.forbid_delete() returns trigger language plpgsql as $$
begin
  raise exception 'Purchasing records cannot be deleted; cancel or reverse them instead' using errcode = '23000';
end $$;
create trigger goods_receipt_no_delete before delete on purchasing.goods_receipt
  for each row execute function purchasing.forbid_delete();
create trigger supplier_bill_no_delete before delete on purchasing.supplier_bill
  for each row execute function purchasing.forbid_delete();
create trigger supplier_price_immutable before update or delete on purchasing.supplier_price
  for each row execute function kernel.forbid_change();

-- A bill's lines can change only while the bill is a draft.
create function purchasing.protect_bill_lines() returns trigger language plpgsql as $$
declare current_status text;
begin
  select status into current_status from purchasing.supplier_bill
    where id = coalesce(old.bill_id, new.bill_id);
  if current_status is not null and current_status <> 'draft' then
    raise exception 'The lines of a bill that has been submitted cannot be changed' using errcode = '23000';
  end if;
  return coalesce(new, old);
end $$;
create trigger supplier_bill_line_protected before update or delete on purchasing.supplier_bill_line
  for each row execute function purchasing.protect_bill_lines();
