alter table finance.expense drop constraint expense_paid_from_check;
update finance.expense set paid_from = 'mpesa' where paid_from = 'mobile_money';
alter table finance.expense add constraint expense_paid_from_check
  check (paid_from in ('cash', 'bank', 'mpesa', 'card', 'other'));
update finance.posting_rule set line_role = 'mpesa_clearing' where line_role = 'mobile_money_clearing';
update finance.posting_rule set line_role = 'mpesa' where line_role = 'mobile_money';
update finance.account set subtype = 'mpesa_clearing' where subtype = 'mobile_money_clearing';
