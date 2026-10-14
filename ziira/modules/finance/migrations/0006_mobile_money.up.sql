-- The clearing account for mobile money is "mobile money clearing", and the roles and methods that said "mpesa" say
-- "mobile_money". Accounts still carrying the old default names are renamed; a name the business chose is left alone.
update finance.account set subtype = 'mobile_money_clearing' where subtype = 'mpesa_clearing';
update finance.account set name = 'Mobile money clearing' where name = 'M-Pesa clearing';
update finance.account set name = 'Bank and mobile money charges' where name = 'Bank and M-Pesa charges';
update finance.posting_rule set line_role = 'mobile_money' where line_role = 'mpesa';
update finance.posting_rule set line_role = 'mobile_money_clearing' where line_role = 'mpesa_clearing';

alter table finance.expense drop constraint expense_paid_from_check;
update finance.expense set paid_from = 'mobile_money' where paid_from = 'mpesa';
alter table finance.expense add constraint expense_paid_from_check
  check (paid_from in ('cash', 'bank', 'mobile_money', 'card', 'other'));
