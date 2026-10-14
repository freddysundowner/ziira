drop index if exists finance.expense_company_date;
alter table finance.expense drop constraint if exists expense_tax_check;
alter table finance.expense drop constraint if exists expense_status_check;
update finance.expense set status = 'posted' where status = 'reversed';
alter table finance.expense add constraint expense_status_check
  check (status in ('draft', 'pending_approval', 'approved', 'posted', 'rejected'));
alter table finance.expense
  drop column if exists reverse_reason, drop column if exists reversed_at, drop column if exists entry_id,
  drop column if exists receipt_ref, drop column if exists paid_from, drop column if exists description;
