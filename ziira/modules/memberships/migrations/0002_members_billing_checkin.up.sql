-- Memberships 0002 · member profiles (photo, card, emergency contact, waiver), households, richer plans, billing state
-- (arrears, grace, dunning, freezes, price changes) and check-in with the access decision.

-- ---------------------------------------------------------------------------------------------------- plans
alter table memberships.plan
  add column kind text not null default 'recurring' check (kind in ('recurring', 'fixed_term', 'pass')),
  add column valid_days integer check (valid_days is null or valid_days between 1 and 3660),
  add column is_trial boolean not null default false,
  add column term_periods integer check (term_periods is null or term_periods between 1 and 120),
  add column notice_days integer not null default 0 check (notice_days between 0 and 365),
  add column early_exit_fee numeric(18,2) not null default 0 check (early_exit_fee >= 0),
  add column joining_fee numeric(18,2) not null default 0 check (joining_fee >= 0),
  add column joining_fee_product_id uuid,
  add column freeze_max_days integer check (freeze_max_days is null or freeze_max_days >= 0),
  add column freeze_fee numeric(18,2) not null default 0 check (freeze_fee >= 0),
  add column prorate boolean,
  add column access_rules jsonb not null default '[]',
  add column branch_ids jsonb not null default '[]',
  add column gym_access boolean not null default true,
  add column classes_mode text not null default 'included' check (classes_mode in ('included', 'credits', 'none')),
  add column guest_passes_per_period integer not null default 0 check (guest_passes_per_period between 0 and 100),
  add column description text,
  add column is_example boolean not null default false;
comment on column memberships.plan.kind is 'recurring (renews until cancelled), fixed_term (a contract of term_periods), pass (day/week/trial: valid_days, no renewal).';
comment on column memberships.plan.access_rules is 'Time windows the plan allows entry in, e.g. off-peak: [{"days":[1,2,3,4,5],"from":"10:00","to":"16:00"}]. Empty: any time.';
comment on column memberships.plan.branch_ids is 'Branches the plan may enter. Empty: every branch of the company.';
comment on column memberships.plan.is_example is 'A plan an industry pack added with an example price; cleared when the business edits the fee.';

-- ---------------------------------------------------------------------------------------------------- settings
alter table memberships.setting
  add column grace_days integer not null default 7 check (grace_days between 0 and 90),
  add column dunning_days text not null default '1,7,14',
  add column auto_freeze_days integer not null default 0 check (auto_freeze_days between 0 and 365),
  add column inactive_weeks integer not null default 0 check (inactive_weeks between 0 and 52),
  add column birthday_messages boolean not null default false,
  add column waiver_required boolean not null default false,
  add column repeat_window_minutes integer not null default 10 check (repeat_window_minutes between 0 and 720),
  add column expiry_warning_days integer not null default 7 check (expiry_warning_days between 0 and 60),
  add column late_cancel_hours integer not null default 0 check (late_cancel_hours between 0 and 168),
  add column late_cancel_consumes boolean not null default true,
  add column no_show_consumes boolean not null default true,
  add column points_per_unit numeric(10,4) not null default 0 check (points_per_unit >= 0),
  add column point_value numeric(10,4) not null default 0 check (point_value >= 0),
  add column referral_reward numeric(18,2) not null default 0 check (referral_reward >= 0),
  add column auto_apply_credit boolean not null default true,
  add column voucher_product_id uuid,
  add column offline_valid_hours integer not null default 24 check (offline_valid_hours between 1 and 168);

-- ---------------------------------------------------------------------------------------------------- households
create table memberships.account_group (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  kind text not null default 'household' check (kind in ('household', 'corporate')),
  payer_customer_id uuid not null,
  notes text,
  status text not null default 'active' check (status in ('active', 'closed'))
);
comment on table memberships.account_group is 'A family or company whose members are billed to one payer.';
alter table memberships.account_group enable row level security;
alter table memberships.account_group force row level security;
create policy tenant_isolation on memberships.account_group
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- ---------------------------------------------------------------------------------------------------- profiles
create table memberships.profile (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  customer_id uuid not null,
  number text not null,
  card_number text,
  lifecycle text not null default 'member' check (lifecycle in ('prospect', 'trial', 'member', 'former')),
  trial_started_on date,
  trial_ends_on date,
  date_of_birth date,
  emergency_name text,
  emergency_phone text,
  emergency_relation text,
  photo_file_id uuid,
  source text,
  referred_by_customer_id uuid,
  group_id uuid references memberships.account_group(id),
  tags jsonb not null default '[]',
  access_blocked boolean not null default false,
  block_reason text,
  notes text,
  last_visit_on date,
  last_visit_at timestamptz,
  birthday_notice_year integer,
  inactive_notice_for date,
  trial_notice_sent boolean not null default false,
  unique (company_id, customer_id),
  unique (company_id, number)
);
comment on table memberships.profile is 'The gym/studio side of a customer: member number, card, photo, emergency contact, household, trial. No health data.';
create unique index profile_card_ix on memberships.profile (company_id, card_number) where card_number is not null;
create index profile_customer_ix on memberships.profile (customer_id);
create index profile_group_ix on memberships.profile (group_id) where group_id is not null;
create index profile_lastvisit_ix on memberships.profile (company_id, last_visit_on);
alter table memberships.profile enable row level security;
alter table memberships.profile force row level security;
create policy tenant_isolation on memberships.profile
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- ---------------------------------------------------------------------------------------------------- waivers
create table memberships.waiver_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  version integer not null check (version > 0),
  title text not null,
  body text not null,
  unique (company_id, version)
);
comment on table memberships.waiver_version is 'A version of the terms/waiver a member accepts. Never edited: a change is a new version.';
create trigger waiver_version_immutable before update or delete on memberships.waiver_version
  for each row execute function kernel.forbid_change();
alter table memberships.waiver_version enable row level security;
alter table memberships.waiver_version force row level security;
create policy tenant_isolation on memberships.waiver_version
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.waiver_acceptance (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid not null,
  version_id uuid not null references memberships.waiver_version(id),
  version integer not null,
  accepted_at timestamptz not null default now(),
  accepted_name text not null,
  method text not null default 'desk' check (method in ('desk', 'kiosk', 'online')),
  note text,
  unique (customer_id, version_id)
);
comment on table memberships.waiver_acceptance is 'Who accepted which version of the terms, when and how (typed name; recorded_by = created_by). Never edited.';
create index waiver_acceptance_customer_ix on memberships.waiver_acceptance (customer_id);
create trigger waiver_acceptance_immutable before update or delete on memberships.waiver_acceptance
  for each row execute function kernel.forbid_change();
alter table memberships.waiver_acceptance enable row level security;
alter table memberships.waiver_acceptance force row level security;
create policy tenant_isolation on memberships.waiver_acceptance
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- ---------------------------------------------------------------------------------------------------- members
alter table memberships.member
  add column billing_customer_id uuid,
  add column term_end date,
  add column price_locked boolean not null default false,
  add column pending_plan_id uuid references memberships.plan(id),
  add column pending_from date,
  add column past_due_since date,
  add column arrears numeric(18,2) not null default 0,
  add column hold_kind text check (hold_kind in ('member', 'business', 'arrears')),
  add column is_trial boolean not null default false,
  add column joining_fee_charged numeric(18,2) not null default 0;
comment on column memberships.member.billing_customer_id is 'Who is invoiced (a parent, a company). Empty: the member themselves.';
comment on column memberships.member.price_locked is 'True: a later change of the plan price from a date does not apply to this member.';
create index member_billing_ix on memberships.member (billing_customer_id) where billing_customer_id is not null;
create index member_pastdue_ix on memberships.member (company_id) where past_due_since is not null;

alter table memberships.package
  add column guest boolean not null default false,
  add column is_example boolean not null default false,
  add column description text;

alter table memberships.sold_package
  add column billing_customer_id uuid;

-- ---------------------------------------------------------------------------------------------------- invoice runs
alter table memberships.invoice_run drop constraint invoice_run_owner_type_check;
alter table memberships.invoice_run add constraint invoice_run_owner_type_check
  check (owner_type in ('schedule', 'member', 'package', 'freeze', 'change', 'exit', 'rental', 'voucher'));
alter table memberships.invoice_run
  add column due_date date,
  add column settle_state text not null default 'open' check (settle_state in ('open', 'paid', 'credited', 'cancelled')),
  add column outstanding numeric(18,2),
  add column dunning_paused boolean not null default false;
create index invoice_run_open_ix on memberships.invoice_run (company_id, due_date)
  where status = 'issued' and settle_state = 'open';
create index invoice_run_customer_ix on memberships.invoice_run (customer_id);

create table memberships.dunning_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  run_id uuid not null references memberships.invoice_run(id),
  step_days integer not null,
  customer_id uuid not null,
  channel text,
  outcome text not null check (outcome in ('queued', 'no_contact')),
  unique (run_id, step_days)
);
comment on table memberships.dunning_log is 'Which late-payment reminder steps were sent for an invoice, once each.';
alter table memberships.dunning_log enable row level security;
alter table memberships.dunning_log force row level security;
create policy tenant_isolation on memberships.dunning_log
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- ---------------------------------------------------------------------------------------------------- price changes and freezes
create table memberships.plan_price_change (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  plan_id uuid not null references memberships.plan(id),
  effective_from date not null,
  fee numeric(18,2) not null check (fee >= 0),
  apply_to_existing boolean not null default false,
  note text,
  status text not null default 'scheduled' check (status in ('scheduled', 'cancelled')),
  unique (plan_id, effective_from)
);
comment on table memberships.plan_price_change is 'A new price for a plan from a date. New members pay it from then; existing members only if apply_to_existing and not price-locked, at the first renewal on or after the date.';
alter table memberships.plan_price_change enable row level security;
alter table memberships.plan_price_change force row level security;
create policy tenant_isolation on memberships.plan_price_change
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.freeze (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  member_id uuid not null references memberships.member(id),
  kind text not null check (kind in ('member', 'business', 'arrears')),
  started_on date not null,
  planned_resume_on date,
  ended_on date,
  days integer,
  fee numeric(18,2) not null default 0,
  reason text
);
comment on table memberships.freeze is 'Each hold on a membership: when it started and ended, how many days, the fee charged.';
create index freeze_member_ix on memberships.freeze (member_id, started_on);
alter table memberships.freeze enable row level security;
alter table memberships.freeze force row level security;
create policy tenant_isolation on memberships.freeze
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- ---------------------------------------------------------------------------------------------------- check-in
create table memberships.checkin (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  customer_id uuid not null,
  member_id uuid,
  holder_type text check (holder_type in ('membership', 'package', 'pass', 'guest', 'none')),
  holder_id uuid,
  local_id text,
  occurred_at timestamptz not null default now(),
  business_date date not null,
  method text not null check (method in ('desk', 'scan', 'card', 'kiosk', 'api', 'class')),
  identifier text,
  device text,
  decision text not null check (decision in ('allow', 'warn', 'deny')),
  reasons jsonb not null default '[]',
  overridden boolean not null default false,
  override_reason text,
  counted boolean not null default false,
  credit_entry_id uuid,
  offline boolean not null default false,
  unique (company_id, local_id)
);
comment on table memberships.checkin is 'Every entry attempt: who, where, how, the decision and its reasons, and a staff override with its reason. Never edited.';
create unique index checkin_one_visit_a_day on memberships.checkin (customer_id, business_date) where counted;
create index checkin_company_time_ix on memberships.checkin (company_id, occurred_at desc);
create index checkin_customer_ix on memberships.checkin (customer_id, occurred_at desc);
create index checkin_branch_day_ix on memberships.checkin (branch_id, business_date);
create trigger checkin_immutable before update or delete on memberships.checkin
  for each row execute function kernel.forbid_change();
alter table memberships.checkin enable row level security;
alter table memberships.checkin force row level security;
create policy tenant_isolation on memberships.checkin
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table memberships.guest_visit (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  host_member_id uuid not null references memberships.member(id),
  host_customer_id uuid not null,
  guest_name text not null,
  guest_phone text,
  visited_on date not null,
  period_start date not null,
  lead_id uuid,
  note text
);
comment on table memberships.guest_visit is 'A guest a member brought in with one of their guest passes.';
create index guest_visit_host_ix on memberships.guest_visit (host_member_id, period_start);
alter table memberships.guest_visit enable row level security;
alter table memberships.guest_visit force row level security;
create policy tenant_isolation on memberships.guest_visit
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
