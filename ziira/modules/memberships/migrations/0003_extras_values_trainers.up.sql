-- Memberships 0003 · gift vouchers, loyalty points and referral credit (a value ledger), lockers, member-shared
-- measurements, trainer rates and earnings.

create table memberships.value_account (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  kind text not null check (kind in ('gift', 'referral', 'promo', 'points')),
  customer_id uuid,
  purchaser_customer_id uuid,
  code text,
  initial numeric(18,2) not null default 0 check (initial >= 0),
  expires_on date,
  status text not null default 'active' check (status in ('active', 'used', 'expired', 'void')),
  note text,
  expiry_notice_for date,
  unique (company_id, code)
);
comment on table memberships.value_account is 'Money-like value a customer holds: a gift voucher (bearer code), referral credit or promo credit (owned by a customer), or loyalty points (one account per customer).';
create unique index value_account_points_ix on memberships.value_account (company_id, customer_id) where kind = 'points';
create index value_account_customer_ix on memberships.value_account (customer_id) where customer_id is not null;
alter table memberships.value_account enable row level security;
alter table memberships.value_account force row level security;
create policy tenant_isolation on memberships.value_account
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.value_entry (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  account_id uuid not null references memberships.value_account(id),
  seq bigint generated always as identity,
  entry_type text not null check (entry_type in ('issue', 'earn', 'redeem', 'refund', 'expiry', 'adjustment', 'reversal')),
  quantity numeric(18,2) not null check (quantity <> 0),
  source_type text,
  source_id uuid,
  reverses_id uuid references memberships.value_entry(id),
  business_date date not null,
  note text
);
comment on table memberships.value_entry is 'The value ledger: every change of a voucher, credit or points balance; never updated or deleted.';
create index value_entry_account_ix on memberships.value_entry (account_id, seq);
create index value_entry_source_ix on memberships.value_entry (source_type, source_id) where entry_type = 'redeem';
create unique index value_entry_reversed_once on memberships.value_entry (reverses_id) where reverses_id is not null;
create unique index value_entry_earn_once on memberships.value_entry (account_id, source_type, source_id) where entry_type = 'earn';
create trigger value_entry_immutable before update or delete on memberships.value_entry
  for each row execute function kernel.forbid_change();
alter table memberships.value_entry enable row level security;
alter table memberships.value_entry force row level security;
create policy tenant_isolation on memberships.value_entry
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.locker (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  code text not null,
  kind text not null default 'locker' check (kind in ('locker', 'towel', 'other')),
  fee numeric(18,2) not null default 0 check (fee >= 0),
  deposit numeric(18,2) not null default 0 check (deposit >= 0),
  billing_interval text not null default 'month' check (billing_interval in ('week', 'month', 'quarter', 'year')),
  product_id uuid,
  status text not null default 'free' check (status in ('free', 'assigned', 'out_of_service')),
  customer_id uuid,
  assigned_on date,
  schedule_id uuid references memberships.schedule(id),
  deposit_run_id uuid,
  note text,
  unique (branch_id, code)
);
comment on table memberships.locker is 'A locker, towel set or other rentable item: who has it, the recurring fee (a recurring invoice) and the deposit.';
alter table memberships.locker enable row level security;
alter table memberships.locker force row level security;
create policy tenant_isolation on memberships.locker
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.measurement (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid not null,
  taken_on date not null,
  metric text not null,
  value numeric(12,3) not null,
  unit text,
  note text
);
comment on table memberships.measurement is 'Measurements a member chooses to share with their trainer (weight, waist, a lift). Not medical records.';
create index measurement_customer_ix on memberships.measurement (customer_id, metric, taken_on);
alter table memberships.measurement enable row level security;
alter table memberships.measurement force row level security;
create policy tenant_isolation on memberships.measurement
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.trainer_rate (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  trainer_ref uuid not null,
  trainer_name text not null,
  service_ref text,
  basis text not null check (basis in ('fixed', 'percent')),
  amount numeric(18,2) not null check (amount >= 0),
  status text not null default 'active' check (status in ('active', 'retired'))
);
comment on table memberships.trainer_rate is 'What a trainer is paid per session: a fixed amount or a percent of the session value, for one service or all.';
create unique index trainer_rate_one_ix on memberships.trainer_rate (company_id, trainer_ref, coalesce(service_ref, ''))
  where status = 'active';
alter table memberships.trainer_rate enable row level security;
alter table memberships.trainer_rate force row level security;
create policy tenant_isolation on memberships.trainer_rate
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.trainer_earning (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  trainer_ref uuid not null,
  trainer_name text not null,
  customer_id uuid,
  service_ref text,
  source_type text not null,
  source_id uuid not null,
  session_value numeric(18,2) not null default 0,
  amount numeric(18,2) not null,
  basis text not null,
  earned_on date not null,
  status text not null default 'earned' check (status in ('earned', 'reversed', 'paid')),
  paid_on date,
  note text,
  unique (source_type, source_id, trainer_ref)
);
comment on table memberships.trainer_earning is 'One row per session a trainer delivered and what they earn for it. Payroll reads it; nothing is paid from here.';
create index trainer_earning_ix on memberships.trainer_earning (company_id, trainer_ref, earned_on);
alter table memberships.trainer_earning enable row level security;
alter table memberships.trainer_earning force row level security;
create policy tenant_isolation on memberships.trainer_earning
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- Whom an invoice is for when someone else pays (a parent for a learner, a company for an employee): the billing contact
-- stays `customer_id`; these two say what the invoice is for.
alter table memberships.schedule
  add column for_customer_id uuid,
  add column for_label text;
alter table memberships.invoice_run
  add column for_customer_id uuid,
  add column for_label text;
