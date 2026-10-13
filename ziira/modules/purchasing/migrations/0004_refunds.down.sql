drop trigger if exists supplier_refund_protected on purchasing.supplier_refund;
drop function if exists purchasing.protect_refund();
drop table if exists purchasing.supplier_refund;
alter table purchasing.supplier_bill drop constraint if exists supplier_bill_refunded_check;
alter table purchasing.supplier_bill drop column if exists refunded;
