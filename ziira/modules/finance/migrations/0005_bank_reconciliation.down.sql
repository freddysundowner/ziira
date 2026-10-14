drop table if exists finance.reconciliation_line;
drop index if exists finance.bank_reconciliation_one_open;
alter table finance.bank_reconciliation drop column if exists cleared_balance, drop column if exists account_id;
