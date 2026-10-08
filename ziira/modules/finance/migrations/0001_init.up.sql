-- Ziira Core 1.0 · schema 'finance' (Finance and Accounting) · install migration
-- Requires: kernel
-- Chart of accounts, journals, periods, expenses and bank reconciliation.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists finance;

create table finance.account (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  type text not null check (type in ('asset', 'liability', 'equity', 'income', 'expense')),
  subtype text,
  parent_id uuid references finance.account(id),
  is_control boolean not null default false,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table finance.account is 'Chart of accounts.';
comment on column finance.account.subtype is 'cash, bank, mpesa_clearing, receivable, payable, inventory, vat_input, vat_output, cogs, ...';
comment on column finance.account.is_control is 'Sub-ledger control account; no manual posting';
alter table finance.account enable row level security;
alter table finance.account force row level security;
create policy tenant_isolation on finance.account
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table finance.period (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  start_date date not null,
  end_date date not null,
  status text not null default 'open' check (status in ('open', 'soft_closed', 'locked')),
  closed_by uuid references kernel.app_user(id),
  closed_at timestamptz,
  unique (company_id, start_date),
  check (end_date >= start_date)
);
comment on table finance.period is 'Accounting periods.';
alter table finance.period enable row level security;
alter table finance.period force row level security;
create policy tenant_isolation on finance.period
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table finance.posting_rule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  doc_type text not null,
  line_role text not null,
  account_id uuid not null references finance.account(id),
  side text not null check (side in ('debit', 'credit')),
  conditions jsonb not null default '{}',
  priority integer not null default 100
);
comment on table finance.posting_rule is 'Maps document lines to accounts.';
comment on column finance.posting_rule.doc_type is 'e.g. sale, goods_receipt, payroll';
comment on column finance.posting_rule.line_role is 'e.g. revenue, vat_output, cogs, inventory';
comment on column finance.posting_rule.conditions is 'e.g. payment method, product category';
create index posting_rule_ix1 on finance.posting_rule (company_id, doc_type);
alter table finance.posting_rule enable row level security;
alter table finance.posting_rule force row level security;
create policy tenant_isolation on finance.posting_rule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table finance.journal (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  unique (company_id, code)
);
comment on table finance.journal is 'Journal books.';
comment on column finance.journal.code is 'SAL, PUR, CSH, PAY, GEN';
alter table finance.journal enable row level security;
alter table finance.journal force row level security;
create policy tenant_isolation on finance.journal
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table finance.journal_entry (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  journal_id uuid not null references finance.journal(id),
  period_id uuid not null references finance.period(id),
  number text not null,
  entry_date date not null,
  source_type text,
  source_id uuid,
  description text,
  is_manual boolean not null default false,
  reversal_of_id uuid references finance.journal_entry(id),
  approved_by uuid references kernel.app_user(id),
  posted_at timestamptz not null default now(),
  unique (company_id, number)
);
comment on table finance.journal_entry is 'A balanced accounting entry.';
comment on column finance.journal_entry.source_type is 'Originating document type; null for manual';
create index journal_entry_ix1 on finance.journal_entry (source_type, source_id);
create index journal_entry_ix2 on finance.journal_entry (company_id, entry_date);
alter table finance.journal_entry enable row level security;
alter table finance.journal_entry force row level security;
create policy tenant_isolation on finance.journal_entry
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger journal_entry_immutable before update or delete on finance.journal_entry
  for each row execute function kernel.forbid_change();

create table finance.journal_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  entry_id uuid not null references finance.journal_entry(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  account_id uuid not null references finance.account(id),
  debit numeric(18,2) not null default 0 check (debit >= 0),
  credit numeric(18,2) not null default 0 check (credit >= 0),
  party_type text,
  party_id uuid,
  description text,
  check ((debit = 0) <> (credit = 0))
);
comment on table finance.journal_line is 'Debit or credit line. Entries must balance.';
create index journal_line_ix1 on finance.journal_line (account_id, company_id);
create index journal_line_ix2 on finance.journal_line (entry_id);
create index journal_line_ix3 on finance.journal_line (party_type, party_id);
alter table finance.journal_line enable row level security;
alter table finance.journal_line force row level security;
create policy tenant_isolation on finance.journal_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger journal_line_immutable before update or delete on finance.journal_line
  for each row execute function kernel.forbid_change();

create table finance.expense (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  expense_date date not null,
  payee text,
  account_id uuid not null references finance.account(id),
  amount numeric(18,2) not null check (amount > 0),
  tax_amount numeric(18,2) not null default 0,
  paid_from_account_id uuid,
  receipt_file_id uuid references kernel.file(id),
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'approved', 'posted', 'rejected')),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number)
);
comment on table finance.expense is 'An expense or petty cash claim.';
comment on column finance.expense.paid_from_account_id is 'Soft reference to payments.payment_account';
alter table finance.expense enable row level security;
alter table finance.expense force row level security;
create policy tenant_isolation on finance.expense
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table finance.bank_reconciliation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  payment_account_id uuid not null,
  statement_date date not null,
  statement_balance numeric(18,2) not null,
  book_balance numeric(18,2) not null,
  difference numeric(18,2) not null,
  status text not null default 'in_progress' check (status in ('in_progress', 'completed')),
  completed_by uuid references kernel.app_user(id),
  completed_at timestamptz
);
comment on table finance.bank_reconciliation is 'Reconciliation of a bank or M-Pesa account to a statement.';
comment on column finance.bank_reconciliation.payment_account_id is 'Soft reference to payments.payment_account';
alter table finance.bank_reconciliation enable row level security;
alter table finance.bank_reconciliation force row level security;
create policy tenant_isolation on finance.bank_reconciliation
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create or replace function finance.check_entry_balanced() returns trigger
  language plpgsql as $$
declare d numeric; c numeric;
begin
  select coalesce(sum(debit), 0), coalesce(sum(credit), 0) into d, c
    from finance.journal_line where entry_id = new.entry_id;
  if d <> c then
    raise exception 'Journal entry % is not balanced: debit %, credit %', new.entry_id, d, c;
  end if;
  return null;
end $$;
create constraint trigger journal_line_balanced
  after insert on finance.journal_line
  deferrable initially deferred
  for each row execute function finance.check_entry_balanced();


