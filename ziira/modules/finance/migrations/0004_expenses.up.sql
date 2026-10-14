-- Expenses (the table exists since 0001): a cost paid at once from cash, bank, M-Pesa or card, with the receipt reference
-- and an approval step. Costs bought on credit go through Purchasing's supplier bills, so accounts payable stays equal to
-- what the supplier ledger says. `amount` is everything paid and includes `tax_amount` (VAT input).

alter table finance.expense
  add column description text not null default '',
  add column paid_from text not null default 'cash' check (paid_from in ('cash', 'bank', 'mpesa', 'card', 'other')),
  add column receipt_ref text,
  add column entry_id uuid references finance.journal_entry(id),
  add column reversed_at timestamptz,
  add column reverse_reason text;
alter table finance.expense alter column description drop default;
alter table finance.expense alter column paid_from drop default;
alter table finance.expense drop constraint expense_status_check;
alter table finance.expense add constraint expense_status_check
  check (status in ('draft', 'pending_approval', 'approved', 'posted', 'rejected', 'reversed'));
alter table finance.expense add constraint expense_tax_check check (tax_amount >= 0 and tax_amount < amount);
create index expense_company_date on finance.expense (company_id, expense_date desc);
comment on column finance.expense.amount is 'Everything paid, VAT included';
