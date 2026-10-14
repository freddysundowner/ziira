alter table purchasing.supplier_refund disable trigger user;
update purchasing.supplier_refund set method = 'mpesa' where method = 'mobile_money';
alter table purchasing.supplier_refund enable trigger user;
alter table purchasing.supplier_bank_account drop constraint supplier_bank_account_method_check;
update purchasing.supplier_bank_account set method = 'mpesa' where method = 'mobile_money';
alter table purchasing.supplier_bank_account add constraint supplier_bank_account_method_check
  check (method in ('bank', 'mpesa'));
