drop trigger if exists customer_refund_protected on pos.customer_refund;
drop function if exists pos.protect_refund();
drop table if exists pos.customer_refund;
alter table pos.customer_receipt drop constraint if exists customer_receipt_balances_check;
alter table pos.customer_receipt drop column if exists refunded;
alter table pos.customer_receipt drop column if exists unallocated;
