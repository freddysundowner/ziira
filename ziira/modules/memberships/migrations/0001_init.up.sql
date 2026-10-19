-- Ziira Core 1.0 · schema 'memberships' (Memberships, packages and recurring invoices) · install migration
-- Requires: kernel, crm (customers are soft references: a plain uuid checked through crm.public)

create schema if not exists memberships;

create table memberships.setting (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null unique references kernel.company(id),
  allow_overdraw boolean not null default false,
  catch_up_max_periods integer not null default 3 check (catch_up_max_periods between 1 and 24),
  prorate_first_period boolean not null default false,
  reminders_enabled boolean not null default true,
  renewal_reminder_days integer not null default 7 check (renewal_reminder_days between 0 and 60),
  expiry_reminder_days integer not null default 14 check (expiry_reminder_days between 0 and 120),
  quiet_start smallint not null default 21 check (quiet_start between 0 and 23),
  quiet_end smallint not null default 7 check (quiet_end between 0 and 23),
  message_language text not null default 'en' check (message_language in ('en', 'sw'))
);
comment on table memberships.setting is 'A company''s membership policies (one row; defaults apply when there is none).';
alter table memberships.setting enable row level security;
alter table memberships.setting force row level security;
create policy tenant_isolation on memberships.setting
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.plan (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  fee numeric(18,2) not null check (fee >= 0),
  billing_interval text not null check (billing_interval in ('month', 'quarter', 'year')),
  credits_per_period numeric(18,2) not null default 0 check (credits_per_period >= 0),
  discount_percent numeric(5,2) not null default 0 check (discount_percent between 0 and 100),
  covered_services jsonb not null default '[]',
  rollover boolean not null default false,
  service_product_id uuid,
  terms text,
  status text not null default 'active' check (status in ('active', 'retired')),
  unique (company_id, code)
);
comment on table memberships.plan is 'A membership plan: fee, billing interval, visits included and discount on services.';
alter table memberships.plan enable row level security;
alter table memberships.plan force row level security;
create policy tenant_isolation on memberships.plan
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.package (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  credits numeric(18,2) not null check (credits > 0),
  price numeric(18,2) not null check (price >= 0),
  expiry_days integer check (expiry_days is null or expiry_days > 0),
  covered_services jsonb not null default '[]',
  product_id uuid,
  terms text,
  status text not null default 'active' check (status in ('active', 'retired')),
  unique (company_id, code)
);
comment on table memberships.package is 'A session package that can be sold (for example 10 massages): credits, price, expiry, services covered.';
alter table memberships.package enable row level security;
alter table memberships.package force row level security;
create policy tenant_isolation on memberships.package
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.member (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  customer_id uuid not null,
  plan_id uuid not null references memberships.plan(id),
  plan_name text not null,
  status text not null default 'active' check (status in ('active', 'paused', 'frozen', 'cancelled', 'expired')),
  start_date date not null,
  current_period_start date not null,
  next_renewal_date date not null,
  anchor_day integer not null default 1 check (anchor_day between 1 and 31),
  end_date date,
  paused_from date,
  resume_on date,
  cancel_at date,
  cancelled_on date,
  cancel_reason_code_id uuid references kernel.reason_code(id),
  cancel_note text,
  price numeric(18,2) not null check (price >= 0),
  billing_interval text not null check (billing_interval in ('month', 'quarter', 'year')),
  credits_per_period numeric(18,2) not null default 0,
  discount_percent numeric(5,2) not null default 0,
  covered_services jsonb not null default '[]',
  rollover boolean not null default false,
  service_product_id uuid,
  auto_invoice boolean not null default true,
  reminded_for date,
  notes text,
  unique (company_id, number)
);
comment on table memberships.member is 'A customer''s membership. Price, interval, credits and discount are copied from the plan when it starts.';
create unique index member_one_live_per_plan on memberships.member (customer_id, plan_id)
  where status in ('active', 'paused', 'frozen');
create index member_customer_ix on memberships.member (customer_id);
create index member_renewal_ix on memberships.member (company_id, next_renewal_date) where status = 'active';
alter table memberships.member enable row level security;
alter table memberships.member force row level security;
create policy tenant_isolation on memberships.member
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.member_history (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  member_id uuid not null references memberships.member(id),
  seq bigint generated always as identity,
  action text not null,
  from_status text,
  to_status text,
  note text,
  happened_on date not null
);
comment on table memberships.member_history is 'What happened to a membership and when (started, renewed, paused, resumed, cancelled, expired).';
create index member_history_ix on memberships.member_history (member_id, seq);
alter table memberships.member_history enable row level security;
alter table memberships.member_history force row level security;
create policy tenant_isolation on memberships.member_history
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.sold_package (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  customer_id uuid not null,
  package_id uuid not null references memberships.package(id),
  name text not null,
  credits numeric(18,2) not null,
  price numeric(18,2) not null,
  covered_services jsonb not null default '[]',
  purchased_on date not null,
  expires_on date,
  status text not null default 'active' check (status in ('active', 'expired', 'refunded')),
  expiry_notice_for date,
  notes text,
  unique (company_id, number)
);
comment on table memberships.sold_package is 'A package bought by a customer, with its own credit balance and expiry.';
create index sold_package_customer_ix on memberships.sold_package (customer_id);
create index sold_package_expiry_ix on memberships.sold_package (company_id, expires_on) where status = 'active';
alter table memberships.sold_package enable row level security;
alter table memberships.sold_package force row level security;
create policy tenant_isolation on memberships.sold_package
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.credit_entry (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid not null,
  holder_type text not null check (holder_type in ('membership', 'package')),
  holder_id uuid not null,
  seq bigint generated always as identity,
  entry_type text not null check (entry_type in ('grant', 'purchase', 'use', 'refund', 'expiry', 'adjustment', 'reversal')),
  quantity numeric(18,2) not null check (quantity <> 0),
  service_ref text,
  source_type text,
  source_id uuid,
  reverses_id uuid references memberships.credit_entry(id),
  period_start date,
  business_date date not null,
  note text
);
comment on table memberships.credit_entry is 'The credits ledger. Every change of a balance; never updated or deleted. A balance is the sum of its entries.';
create index credit_entry_holder_ix on memberships.credit_entry (holder_id, seq);
create index credit_entry_customer_ix on memberships.credit_entry (customer_id);
create index credit_entry_use_ix on memberships.credit_entry (source_type, source_id) where entry_type = 'use';
create unique index credit_entry_reversed_once on memberships.credit_entry (reverses_id) where reverses_id is not null;
create unique index credit_entry_grant_once on memberships.credit_entry (holder_id, period_start)
  where entry_type = 'grant';
create trigger credit_entry_immutable before update or delete on memberships.credit_entry
  for each row execute function kernel.forbid_change();
alter table memberships.credit_entry enable row level security;
alter table memberships.credit_entry force row level security;
create policy tenant_isolation on memberships.credit_entry
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.schedule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  customer_id uuid not null,
  name text not null,
  lines jsonb not null,
  billing_interval text not null check (billing_interval in ('week', 'month', 'quarter', 'year')),
  interval_count integer not null default 1 check (interval_count between 1 and 52),
  anchor_day integer check (anchor_day is null or anchor_day between 1 and 31),
  start_date date not null,
  next_index integer not null default 0,
  next_run date not null,
  end_date date,
  max_runs integer check (max_runs is null or max_runs > 0),
  mode text not null default 'issue' check (mode in ('issue', 'draft')),
  status text not null default 'active' check (status in ('active', 'paused', 'ended')),
  resume_on date,
  due_days integer check (due_days is null or due_days between 0 and 365),
  memo text,
  last_run_at timestamptz,
  last_run_status text,
  last_run_message text,
  last_invoice_number text
);
comment on table memberships.schedule is 'A recurring invoice for any customer: lines, interval, next run, end, and whether to issue or leave a draft.';
create index schedule_due_ix on memberships.schedule (company_id, next_run) where status = 'active';
create index schedule_customer_ix on memberships.schedule (customer_id);
alter table memberships.schedule enable row level security;
alter table memberships.schedule force row level security;
create policy tenant_isolation on memberships.schedule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table memberships.invoice_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  customer_id uuid not null,
  owner_type text not null check (owner_type in ('schedule', 'member', 'package')),
  owner_id uuid not null,
  period_start date not null,
  period_end date,
  status text not null check (status in ('issued', 'pending_review', 'failed', 'skipped', 'discarded')),
  attempts integer not null default 0,
  lines jsonb not null default '[]',
  due_days integer,
  memo text,
  total numeric(18,2),
  invoice_id uuid,
  invoice_number text,
  message text,
  unique (owner_type, owner_id, period_start)
);
comment on table memberships.invoice_run is 'One try to invoice one period of a schedule, membership or package. The unique key makes a period invoice once.';
create index invoice_run_status_ix on memberships.invoice_run (company_id, status);
alter table memberships.invoice_run enable row level security;
alter table memberships.invoice_run force row level security;
create policy tenant_isolation on memberships.invoice_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
