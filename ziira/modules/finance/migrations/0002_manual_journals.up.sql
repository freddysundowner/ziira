-- Manual journals wait here (draft, pending approval) until they post as an immutable journal entry.

create table finance.manual_journal (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  journal_id uuid not null references finance.journal(id),
  number text not null,
  entry_date date not null,
  description text not null,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'posted', 'rejected')),
  total numeric(18,2) not null check (total > 0),
  entry_id uuid references finance.journal_entry(id),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number)
);
comment on table finance.manual_journal is 'A manual journal before it is posted.';
alter table finance.manual_journal enable row level security;
alter table finance.manual_journal force row level security;
create policy tenant_isolation on finance.manual_journal
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table finance.manual_journal_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  manual_journal_id uuid not null references finance.manual_journal(id),
  line_no smallint not null,
  account_id uuid not null references finance.account(id),
  branch_id uuid references kernel.branch(id),
  debit numeric(18,2) not null default 0 check (debit >= 0),
  credit numeric(18,2) not null default 0 check (credit >= 0),
  description text,
  check ((debit = 0) <> (credit = 0)),
  unique (manual_journal_id, line_no)
);
comment on table finance.manual_journal_line is 'Lines of a manual journal.';
alter table finance.manual_journal_line enable row level security;
alter table finance.manual_journal_line force row level security;
create policy tenant_isolation on finance.manual_journal_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- A reversal can be made once only, and an entry is posted once per source document.
create unique index journal_entry_one_reversal on finance.journal_entry (reversal_of_id) where reversal_of_id is not null;
create unique index journal_entry_one_per_source on finance.journal_entry (company_id, source_type, source_id)
  where source_type is not null and reversal_of_id is null;
