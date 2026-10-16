-- Super admin platform: operator roles, plans and prices (data, effective-dated), coupons, subscriptions, licences, and the
-- vendor's billing records. Nothing here is a country, a currency or a price in code: all of it is rows an operator enters.

-- ---------------------------------------------------------------- operator roles
alter table master.operator add column role text not null default 'superadmin'
  check (role in ('superadmin', 'billing', 'support', 'content', 'readonly'));
comment on column master.operator.role is 'What the operator may do in the Super Admin (permissions per role are in kernel/platform/permissions.py). Operators made before roles existed are superadmins.';

-- ---------------------------------------------------------------- platform settings (vendor details, tax lines, dunning ...)
create table master.platform_setting (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by text
);
comment on table master.platform_setting is 'The platform owner''s own settings: vendor identity for invoices, tax lines, payment instructions, dunning schedule, proration rules, default plan. Typed and validated in kernel/platform/settings.py.';

-- ---------------------------------------------------------------- plans and prices
create table master.plan (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code ~ '^[a-z0-9][a-z0-9_-]{1,39}$'),
  name text not null,
  description text not null default '',
  edition text,
  units text[] not null default '{}',
  addon_units text[] not null default '{}',
  max_users int check (max_users is null or max_users > 0),
  max_branches int check (max_branches is null or max_branches > 0),
  max_companies int check (max_companies is null or max_companies > 0),
  limits jsonb not null default '{}',
  highlights text[] not null default '{}',
  trial_days int not null default 0 check (trial_days >= 0 and trial_days <= 365),
  intervals text[] not null default '{month,year}',
  sort_order int not null default 100,
  is_public boolean not null default false,
  status text not null default 'active' check (status in ('active', 'retired')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
comment on table master.plan is 'What a subscriber can buy: the units and limits it includes. Null limit = unlimited. Retired plans keep working for those on them but cannot be chosen.';

create table master.plan_price (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null references master.plan(id) on delete cascade,
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
  interval text not null check (interval in ('month', 'year', 'one_time')),
  amount numeric(14, 2) not null check (amount >= 0),
  tax_inclusive boolean not null default false,
  withdrawn boolean not null default false,
  effective_from timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by text,
  unique (plan_id, currency, interval, effective_from)
);
create index plan_price_ix on master.plan_price (plan_id, currency, interval, effective_from desc);
comment on table master.plan_price is 'Append-only price history: the price in force at a moment is the row with the latest effective_from not after it. A change is a new row; a withdrawn row means "not offered from then on". Past rows are never changed.';

create table master.addon (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code ~ '^[a-z0-9][a-z0-9_-]{1,39}$'),
  name text not null,
  description text not null default '',
  kind text not null check (kind in ('unit', 'users', 'branches', 'companies')),
  unit_name text,
  quantity int not null default 1 check (quantity > 0),
  is_public boolean not null default false,
  status text not null default 'active' check (status in ('active', 'retired')),
  sort_order int not null default 100,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((kind = 'unit') = (unit_name is not null))
);
comment on table master.addon is 'Something added to a plan: a plugin/unit, or extra users, branches or companies (quantity each).';

create table master.addon_price (
  id uuid primary key default gen_random_uuid(),
  addon_id uuid not null references master.addon(id) on delete cascade,
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
  interval text not null check (interval in ('month', 'year', 'one_time')),
  amount numeric(14, 2) not null check (amount >= 0),
  tax_inclusive boolean not null default false,
  withdrawn boolean not null default false,
  effective_from timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by text,
  unique (addon_id, currency, interval, effective_from)
);
create index addon_price_ix on master.addon_price (addon_id, currency, interval, effective_from desc);

create table master.coupon (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code ~ '^[A-Z0-9][A-Z0-9_-]{2,39}$'),
  description text not null default '',
  percent_off numeric(5, 2) check (percent_off is null or (percent_off > 0 and percent_off <= 100)),
  duration text not null default 'once' check (duration in ('once', 'repeating', 'forever')),
  duration_periods int check (duration_periods is null or duration_periods > 0),
  max_redemptions int check (max_redemptions is null or max_redemptions > 0),
  redeemed int not null default 0,
  expires_at timestamptz,
  plan_codes text[] not null default '{}',
  status text not null default 'active' check (status in ('active', 'disabled')),
  created_at timestamptz not null default now(),
  check ((duration = 'repeating') = (duration_periods is not null))
);
create table master.coupon_amount (
  coupon_id uuid not null references master.coupon(id) on delete cascade,
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
  amount_off numeric(14, 2) not null check (amount_off > 0),
  primary key (coupon_id, currency)
);
comment on table master.coupon is 'A discount: a percentage (percent_off) or a fixed amount per currency (coupon_amount); for one invoice, N invoices or for as long as the subscription lasts.';

-- ---------------------------------------------------------------- subscriptions (SaaS)
create table master.subscription (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null unique references master.tenant(id) on delete cascade,
  plan_id uuid references master.plan(id),
  plan_code text not null,
  plan_name text not null,
  status text not null check (status in ('trialing', 'active', 'past_due', 'grace', 'suspended', 'cancelled', 'expired')),
  interval text not null check (interval in ('month', 'year', 'one_time')),
  currency char(3) not null,
  unit_amount numeric(14, 2) not null default 0,
  tax_inclusive boolean not null default false,
  entitlements jsonb not null default '{}',
  period_start timestamptz,
  period_end timestamptz,
  trial_end timestamptz,
  cancel_at_period_end boolean not null default false,
  coupon_id uuid references master.coupon(id),
  coupon_periods_left int,
  pending_plan_id uuid references master.plan(id),
  pending_interval text,
  pending_currency char(3),
  is_comp boolean not null default false,
  notes text not null default '',
  tags text[] not null default '{}',
  status_reason text,
  status_changed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index subscription_status_ix on master.subscription (status, period_end);
comment on table master.subscription is 'The business''s plan, price and limits as agreed (snapshots: later edits of the plan do not change them) and where it stands. One row per business; its history is subscription_event.';

create table master.subscription_event (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  tenant_id uuid not null,
  kind text not null,
  detail jsonb,
  by_name text
);
create index subscription_event_ix on master.subscription_event (tenant_id, occurred_at);
create index subscription_event_kind_ix on master.subscription_event (kind, occurred_at);

create table master.plan_request (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references master.tenant(id) on delete cascade,
  plan_id uuid not null references master.plan(id),
  interval text not null,
  currency char(3) not null,
  coupon_code text,
  note text not null default '',
  status text not null default 'pending' check (status in ('pending', 'approved', 'declined', 'cancelled')),
  invoice_id uuid,
  requested_by text,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  decided_by text
);
create index plan_request_ix on master.plan_request (tenant_id, status);

create table master.subscriber_deletion (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null,
  tenant_code text not null,
  requested_at timestamptz not null default now(),
  requested_by text not null,
  execute_after timestamptz not null,
  reason text not null,
  cancelled_at timestamptz,
  executed_at timestamptz
);
create unique index subscriber_deletion_open_ix on master.subscriber_deletion (tenant_id)
  where cancelled_at is null and executed_at is null;

-- ---------------------------------------------------------------- licences (outright purchase / self-hosted)
create table master.licence (
  id uuid primary key default gen_random_uuid(),
  licence_no text not null unique,
  customer text not null,
  contact_email text,
  plan_id uuid references master.plan(id),
  plan_code text,
  entitlements jsonb not null default '{}',
  issued_at timestamptz not null default now(),
  valid_until timestamptz,
  update_until timestamptz,
  grace_days int not null default 30,
  instance_id text,
  status text not null default 'active' check (status in ('active', 'revoked')),
  revoked_at timestamptz,
  revoked_reason text,
  token text not null,
  notes text not null default '',
  issued_by text
);
comment on table master.licence is 'Licences the vendor issued (vendor deployment). `token` is the signed file the customer installs; the private key is never stored here.';

create table master.installed_licence (
  singleton boolean primary key default true check (singleton),
  token text not null,
  payload jsonb not null,
  installed_at timestamptz not null default now(),
  installed_by text
);
comment on table master.installed_licence is 'The licence a self-hosted instance runs under (verified with ZIIRA_LICENCE_PUBLIC_KEY on every start).';

create table master.licence_revocation (
  licence_no text primary key,
  revoked_at timestamptz not null default now(),
  reason text
);
comment on table master.licence_revocation is 'Revocations installed from a signed revocation list (self-hosted instance).';

-- ---------------------------------------------------------------- billing records
create table master.billing_counter (
  name text primary key,
  last_value bigint not null default 0
);

create table master.billing_invoice (
  id uuid primary key default gen_random_uuid(),
  number text,
  tenant_id uuid references master.tenant(id) on delete set null,
  licence_id uuid references master.licence(id),
  bill_to jsonb not null default '{}',
  kind text not null default 'manual' check (kind in ('renewal', 'upgrade', 'manual', 'licence', 'first')),
  status text not null default 'draft' check (status in ('draft', 'issued', 'paid', 'void')),
  currency char(3) not null,
  lines jsonb not null default '[]',
  tax_lines jsonb not null default '[]',
  tax_inclusive boolean not null default false,
  subtotal numeric(14, 2) not null default 0,
  discount_total numeric(14, 2) not null default 0,
  tax_total numeric(14, 2) not null default 0,
  total numeric(14, 2) not null default 0,
  amount_paid numeric(14, 2) not null default 0,
  period_start timestamptz,
  period_end timestamptz,
  issue_date date,
  due_date date,
  plan_change jsonb,
  coupon_id uuid,
  notes text not null default '',
  vendor jsonb not null default '{}',
  created_by text,
  created_at timestamptz not null default now(),
  issued_at timestamptz,
  paid_at timestamptz,
  voided_at timestamptz,
  void_reason text
);
create unique index billing_invoice_number_ix on master.billing_invoice (number) where number is not null;
create index billing_invoice_tenant_ix on master.billing_invoice (tenant_id, created_at);
create index billing_invoice_status_ix on master.billing_invoice (status, due_date);
comment on table master.billing_invoice is 'What the vendor bills a subscriber or licence customer. A number is given when it is issued; an issued invoice is never edited, only paid or voided. Tax lines come from the vendor''s settings.';

create table master.billing_payment (
  id uuid primary key default gen_random_uuid(),
  invoice_id uuid not null references master.billing_invoice(id),
  tenant_id uuid,
  method text not null,
  reference text not null default '',
  amount numeric(14, 2) not null check (amount > 0),
  currency char(3) not null,
  paid_on date not null,
  provider text not null default 'manual',
  recorded_by text,
  created_at timestamptz not null default now(),
  reversed_at timestamptz,
  reversed_by text,
  reversal_reason text
);
create index billing_payment_ix on master.billing_payment (invoice_id);

create table master.billing_reminder (
  invoice_id uuid not null references master.billing_invoice(id) on delete cascade,
  offset_days int not null,
  sent_at timestamptz not null default now(),
  primary key (invoice_id, offset_days)
);
