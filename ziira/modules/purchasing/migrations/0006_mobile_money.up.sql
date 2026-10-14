-- The payment method "mpesa" is now "mobile_money" (a relabel of the code on existing rows; protection triggers paused).
alter table purchasing.supplier_bank_account drop constraint supplier_bank_account_method_check;
update purchasing.supplier_bank_account set method = 'mobile_money' where method = 'mpesa';
alter table purchasing.supplier_bank_account add constraint supplier_bank_account_method_check
  check (method in ('bank', 'mobile_money'));

alter table purchasing.supplier_refund disable trigger user;
update purchasing.supplier_refund set method = 'mobile_money' where method = 'mpesa';
alter table purchasing.supplier_refund enable trigger user;
