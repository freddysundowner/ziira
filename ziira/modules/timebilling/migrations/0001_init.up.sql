-- Ziira Core · schema 'timebilling' (Time and Billing) · install migration
-- Requires: kernel, crm
-- Clients' projects, rate cards, timesheets, expenses, retainers and invoice reviews.

create schema if not exists timebilling;

create table timebilling.setting (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id) unique,
  minute_step integer not null default 1 check (minute_step in (1, 5, 6, 10, 15, 30, 60)),
  timer_round_minutes integer not null default 0 check (timer_round_minutes in (0, 1, 5, 6, 10, 15, 30, 60)),
  timer_round_mode text not null default 'nearest' check (timer_round_mode in ('up', 'nearest', 'down')),
  week_starts_on integer not null default 1 check (week_starts_on between 1 and 7),
  capacity_minutes_week integer not null default 2400 check (capacity_minutes_week between 0 and 10080),
  approval_required boolean not null default true,
  rates_include_tax boolean not null default false,
  service_product_id uuid,
  expense_product_id uuid,
  invoice_round_minutes integer not null default 0 check (invoice_round_minutes in (0, 5, 6, 10, 15, 30, 60)),
  default_group_by text not null default 'project' check (default_group_by in ('project', 'person', 'task', 'day')),
  budget_alert_percent integer not null default 80 check (budget_alert_percent between 1 and 100),
  unsubmitted_after_days integer not null default 3 check (unsubmitted_after_days between 0 and 60),
  unbilled_after_days integer not null default 30 check (unbilled_after_days between 1 and 365),
  notes_retention_days integer check (notes_retention_days is null or notes_retention_days >= 30)
);
comment on table timebilling.setting is 'One row per company: how time is entered, rounded, approved and billed.';
alter table timebilling.setting enable row level security;
alter table timebilling.setting force row level security;
create policy tenant_isolation on timebilling.setting
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.staff (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  user_id uuid not null references kernel.app_user(id),
  title text,
  weekly_capacity_minutes integer check (weekly_capacity_minutes is null or weekly_capacity_minutes between 0 and 10080),
  active boolean not null default true,
  unique (company_id, user_id)
);
comment on table timebilling.staff is 'A person who logs time: their title (for role rates) and weekly capacity.';
alter table timebilling.staff enable row level security;
alter table timebilling.staff force row level security;
create policy tenant_isolation on timebilling.staff
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.client_terms (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid not null,
  payment_terms_days integer check (payment_terms_days is null or payment_terms_days between 0 and 365),
  invoice_group_by text check (invoice_group_by is null or invoice_group_by in ('project', 'person', 'task', 'day')),
  billing_notes text,
  active boolean not null default true,
  unique (company_id, customer_id)
);
comment on table timebilling.client_terms is 'Billing settings for a client (a CRM customer).';
alter table timebilling.client_terms enable row level security;
alter table timebilling.client_terms force row level security;
create policy tenant_isolation on timebilling.client_terms
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.project (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  client_id uuid not null,
  code text not null,
  name text not null,
  status text not null default 'active' check (status in ('active', 'on_hold', 'completed', 'archived')),
  billing_mode text not null default 'time_and_materials' check (billing_mode in ('time_and_materials', 'fixed_fee', 'retainer')),
  budget_minutes integer check (budget_minutes is null or budget_minutes > 0),
  budget_amount numeric(18,2) check (budget_amount is null or budget_amount > 0),
  fixed_fee numeric(18,2) check (fixed_fee is null or fixed_fee >= 0),
  service_product_id uuid,
  manager_id uuid references kernel.app_user(id),
  starts_on date,
  ends_on date,
  notes text,
  unique (company_id, code)
);
comment on table timebilling.project is 'Work done for a client, with a budget and a way of billing.';
alter table timebilling.project enable row level security;
alter table timebilling.project force row level security;
create policy tenant_isolation on timebilling.project
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.milestone (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  project_id uuid not null references timebilling.project(id),
  name text not null,
  amount numeric(18,2) not null check (amount >= 0),
  due_on date,
  status text not null default 'planned' check (status in ('planned', 'ready', 'invoiced')),
  batch_id uuid,
  sort_order integer not null default 0
);
comment on table timebilling.milestone is 'A part of a fixed-fee project that is billed when it is done.';
alter table timebilling.milestone enable row level security;
alter table timebilling.milestone force row level security;
create policy tenant_isolation on timebilling.milestone
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.rate (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  kind text not null check (kind in ('bill', 'cost')),
  project_id uuid references timebilling.project(id),
  client_id uuid,
  user_id uuid references kernel.app_user(id),
  service_product_id uuid,
  role_title text,
  rate numeric(18,2) not null check (rate >= 0),
  effective_from date not null,
  effective_to date,
  note text,
  seq bigint generated by default as identity,
  check (effective_to is null or effective_to >= effective_from)
);
comment on table timebilling.rate is 'A row of a rate card: an hourly rate (billed to clients, or cost to the business) for some work.';
alter table timebilling.rate enable row level security;
alter table timebilling.rate force row level security;
create policy tenant_isolation on timebilling.rate
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.week (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  user_id uuid not null references kernel.app_user(id),
  week_start date not null,
  status text not null default 'draft' check (status in ('draft', 'submitted', 'approved', 'rejected')),
  submitted_at timestamptz,
  decided_by uuid references kernel.app_user(id),
  decided_at timestamptz,
  decision_note text,
  approval_pending boolean not null default false,
  minutes integer not null default 0,
  unique (company_id, user_id, week_start)
);
comment on table timebilling.week is 'One person''s week of time: submitted, then approved by someone else.';
alter table timebilling.week enable row level security;
alter table timebilling.week force row level security;
create policy tenant_isolation on timebilling.week
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.entry (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  user_id uuid not null references kernel.app_user(id),
  project_id uuid not null references timebilling.project(id),
  task text,
  work_date date not null,
  minutes integer not null check (minutes > 0 and minutes <= 1440),
  billable boolean not null default true,
  note text,
  service_product_id uuid,
  source text not null default 'manual' check (source in ('manual', 'grid', 'timer')),
  started_at timestamptz,
  ended_at timestamptz,
  status text not null default 'draft' check (status in ('draft', 'submitted', 'approved')),
  week_id uuid references timebilling.week(id),
  approved_by uuid references kernel.app_user(id),
  approved_at timestamptz,
  bill_rate numeric(18,2),
  cost_rate numeric(18,2),
  retainer_minutes integer not null default 0 check (retainer_minutes >= 0),
  rate_override numeric(18,2) check (rate_override is null or rate_override >= 0),
  batch_id uuid,
  invoice_id uuid,
  invoiced_at timestamptz,
  check (retainer_minutes <= minutes)
);
comment on table timebilling.entry is 'A block of time a person worked on a project.';
alter table timebilling.entry enable row level security;
alter table timebilling.entry force row level security;
create policy tenant_isolation on timebilling.entry
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.expense (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  user_id uuid not null references kernel.app_user(id),
  project_id uuid not null references timebilling.project(id),
  expense_date date not null,
  description text not null,
  reference text,
  amount numeric(18,2) not null check (amount > 0),
  markup_percent numeric(7,2) not null default 0 check (markup_percent between 0 and 1000),
  billable boolean not null default true,
  status text not null default 'draft' check (status in ('draft', 'submitted', 'approved')),
  week_id uuid references timebilling.week(id),
  approved_by uuid references kernel.app_user(id),
  approved_at timestamptz,
  batch_id uuid,
  invoice_id uuid,
  invoiced_at timestamptz
);
comment on table timebilling.expense is 'Money spent for a client that is billed to them (with an optional markup).';
alter table timebilling.expense enable row level security;
alter table timebilling.expense force row level security;
create policy tenant_isolation on timebilling.expense
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.timer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  user_id uuid not null references kernel.app_user(id) unique,
  project_id uuid not null references timebilling.project(id),
  task text,
  note text,
  billable boolean not null default true,
  service_product_id uuid,
  started_at timestamptz not null,
  resumed_at timestamptz,
  accumulated_seconds integer not null default 0 check (accumulated_seconds >= 0)
);
comment on table timebilling.timer is 'A running (or paused) timer: one per person.';
alter table timebilling.timer enable row level security;
alter table timebilling.timer force row level security;
create policy tenant_isolation on timebilling.timer
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.retainer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  project_id uuid not null references timebilling.project(id),
  kind text not null check (kind in ('hours', 'monthly_fee')),
  monthly_fee numeric(18,2) check (monthly_fee is null or monthly_fee >= 0),
  balance_minutes integer not null default 0,
  topped_up_minutes integer not null default 0,
  expires_on date,
  status text not null default 'active' check (status in ('active', 'closed')),
  alert_percent integer not null default 80 check (alert_percent between 1 and 100),
  note text
);
comment on table timebilling.retainer is 'Prepaid hours or a fixed monthly fee for a project.';
alter table timebilling.retainer enable row level security;
alter table timebilling.retainer force row level security;
create policy tenant_isolation on timebilling.retainer
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.retainer_txn (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  retainer_id uuid not null references timebilling.retainer(id),
  kind text not null check (kind in ('topup', 'drawdown', 'release', 'expire')),
  minutes integer not null default 0,
  amount numeric(18,2),
  entry_id uuid,
  batch_id uuid,
  period text,
  occurred_on date not null,
  note text
);
comment on table timebilling.retainer_txn is 'Every change to a retainer''s balance (never edited).';
alter table timebilling.retainer_txn enable row level security;
alter table timebilling.retainer_txn force row level security;
create policy tenant_isolation on timebilling.retainer_txn
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.invoice_batch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  client_id uuid not null,
  project_id uuid references timebilling.project(id),
  status text not null default 'draft' check (status in ('draft', 'issued', 'cancelled', 'discarded')),
  group_by text not null default 'project' check (group_by in ('project', 'person', 'task', 'day')),
  round_minutes integer not null default 0,
  due_days integer,
  memo text,
  invoice_id uuid,
  invoice_number text,
  total numeric(18,2),
  tax_total numeric(18,2),
  issued_by uuid references kernel.app_user(id),
  issued_at timestamptz,
  released_at timestamptz
);
comment on table timebilling.invoice_batch is 'A review of what to invoice a client: built from approved work, edited, then issued as one invoice.';
alter table timebilling.invoice_batch enable row level security;
alter table timebilling.invoice_batch force row level security;
create policy tenant_isolation on timebilling.invoice_batch
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.invoice_batch_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  batch_id uuid not null references timebilling.invoice_batch(id),
  line_no integer not null,
  kind text not null check (kind in ('time', 'expense', 'milestone', 'retainer_topup', 'retainer_fee', 'manual')),
  project_id uuid references timebilling.project(id),
  description text not null,
  minutes integer,
  rate numeric(18,2),
  amount numeric(18,2) not null,
  service_product_id uuid,
  entry_ids uuid[] not null default '{}',
  expense_ids uuid[] not null default '{}',
  milestone_id uuid,
  retainer_id uuid,
  period text,
  unique (batch_id, line_no)
);
comment on table timebilling.invoice_batch_line is 'One line of an invoice review.';
alter table timebilling.invoice_batch_line enable row level security;
alter table timebilling.invoice_batch_line force row level security;
create policy tenant_isolation on timebilling.invoice_batch_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index entry_user_date on timebilling.entry (user_id, work_date);
create index entry_project_date on timebilling.entry (project_id, work_date);
create index entry_week on timebilling.entry (week_id);
create index entry_unbilled on timebilling.entry (company_id, work_date) where status = 'approved' and billable and invoice_id is null;
create index entry_batch on timebilling.entry (batch_id) where batch_id is not null;
create index expense_project on timebilling.expense (project_id, expense_date);
create index expense_batch on timebilling.expense (batch_id) where batch_id is not null;
create index project_client on timebilling.project (client_id);
create index rate_lookup on timebilling.rate (company_id, kind, effective_from);
create index batch_client on timebilling.invoice_batch (client_id, status);
create index batch_invoice on timebilling.invoice_batch (invoice_id) where invoice_id is not null;
create index retainer_txn_ix on timebilling.retainer_txn (retainer_id, occurred_on);
create unique index retainer_one_active_per_project on timebilling.retainer (project_id) where status = 'active';

-- A retainer's history is never edited or deleted.
create function timebilling.refuse_change() returns trigger language plpgsql as $$
begin
  raise exception 'timebilling.retainer_txn rows cannot be changed or deleted' using errcode = '23000';
end $$;
create trigger retainer_txn_immutable before update or delete on timebilling.retainer_txn
  for each row execute function timebilling.refuse_change();

