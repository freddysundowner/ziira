alter table payments.payment drop constraint payment_method_check;
update payments.payment set method = 'mpesa' where method = 'mobile_money';
alter table payments.payment add constraint payment_method_check
  check (method in ('cash', 'mpesa', 'bank', 'card', 'cheque', 'other'));
alter table payments.payment_account drop constraint payment_account_kind_check;
update payments.payment_account
   set kind = case when config->>'till_type' = 'till' then 'mpesa_till' else 'mpesa_paybill' end
 where kind = 'mobile_money';
alter table payments.payment_account add constraint payment_account_kind_check
  check (kind in ('cash', 'mpesa_till', 'mpesa_paybill', 'bank', 'card'));
