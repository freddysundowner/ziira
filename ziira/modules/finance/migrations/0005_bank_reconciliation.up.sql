-- Bank reconciliation (the table exists since 0001): tick the ledger lines of a bank, M-Pesa or card account that have
-- cleared, until the cleared balance equals the statement's. A line is cleared once; a completed reconciliation is final.

alter table finance.bank_reconciliation
  add column account_id uuid references finance.account(id),
  add column cleared_balance numeric(18,2) not null default 0,
  alter column payment_account_id drop not null;
create unique index bank_reconciliation_one_open on finance.bank_reconciliation (account_id) where status = 'in_progress';

create table finance.reconciliation_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  reconciliation_id uuid not null references finance.bank_reconciliation(id) on delete cascade,
  journal_line_id uuid not null references finance.journal_line(id),
  unique (journal_line_id)
);
comment on table finance.reconciliation_line is 'A journal line that has cleared the bank, in one reconciliation (never two).';
alter table finance.reconciliation_line enable row level security;
alter table finance.reconciliation_line force row level security;
create policy tenant_isolation on finance.reconciliation_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index reconciliation_line_recon on finance.reconciliation_line (reconciliation_id);
