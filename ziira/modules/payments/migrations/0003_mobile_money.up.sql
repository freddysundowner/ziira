-- "Mobile money" is the kind of account and the method of payment; which service provides it (M-Pesa through Daraja, or
-- another) is the account's provider and its settings. Existing M-Pesa data becomes mobile money with a Daraja provider.

alter table payments.payment_account drop constraint payment_account_kind_check;
update payments.payment_account
   set config = config || jsonb_build_object('till_type', case kind when 'mpesa_till' then 'till' else 'paybill' end),
       kind = 'mobile_money'
 where kind in ('mpesa_till', 'mpesa_paybill');
alter table payments.payment_account add constraint payment_account_kind_check
  check (kind in ('cash', 'mobile_money', 'bank', 'card'));

alter table payments.payment drop constraint payment_method_check;
update payments.payment set method = 'mobile_money' where method = 'mpesa';
alter table payments.payment add constraint payment_method_check
  check (method in ('cash', 'mobile_money', 'bank', 'card', 'cheque', 'other'));
