-- Ziira Core 1.0 · schema 'crm' (CRM and Customers) · install migration
-- Requires: kernel
-- Leads, customers, contacts and credit.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists crm;

create table crm.customer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  kind text not null default 'business' check (kind in ('individual', 'business')),
  phone text,
  email text,
  kra_pin text,
  customer_group text,
  credit_limit numeric(18,2) not null default 0,
  payment_terms_days integer not null default 0,
  owner_user_id uuid references kernel.app_user(id),
  status text not null default 'active' check (status in ('active', 'on_hold', 'inactive')),
  unique (company_id, code)
);
comment on table crm.customer is 'A customer.';
comment on column crm.customer.credit_limit is 'Current value; history in customer_credit_version';
comment on column crm.customer.owner_user_id is 'Account manager';
create index customer_ix1 on crm.customer (tenant_id, phone);
alter table crm.customer enable row level security;
alter table crm.customer force row level security;
create policy tenant_isolation on crm.customer
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table crm.customer_contact (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  customer_id uuid not null references crm.customer(id),
  name text not null,
  phone text,
  email text,
  role text
);
comment on table crm.customer_contact is 'People at a business customer.';
alter table crm.customer_contact enable row level security;
alter table crm.customer_contact force row level security;
create policy tenant_isolation on crm.customer_contact
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table crm.customer_credit_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  customer_id uuid not null references crm.customer(id),
  credit_limit numeric(18,2) not null,
  payment_terms_days integer not null,
  valid_from timestamptz not null,
  reason text,
  approved_by uuid references kernel.app_user(id)
);
comment on table crm.customer_credit_version is 'History of credit limit and terms.';
alter table crm.customer_credit_version enable row level security;
alter table crm.customer_credit_version force row level security;
create policy tenant_isolation on crm.customer_credit_version
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table crm.lead_source (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  name text not null,
  unique (tenant_id, name)
);
comment on table crm.lead_source is 'Where leads come from.';
alter table crm.lead_source enable row level security;
alter table crm.lead_source force row level security;
create policy tenant_isolation on crm.lead_source
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table crm.lead (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  business_name text,
  phone text,
  email text,
  source_id uuid references crm.lead_source(id),
  status text not null default 'new' check (status in ('new', 'contacted', 'qualified', 'converted', 'lost')),
  owner_user_id uuid references kernel.app_user(id),
  converted_customer_id uuid references crm.customer(id)
);
comment on table crm.lead is 'A prospective customer.';
alter table crm.lead enable row level security;
alter table crm.lead force row level security;
create policy tenant_isolation on crm.lead
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table crm.activity (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  related_type text not null check (related_type in ('lead', 'customer')),
  related_id uuid not null,
  kind text not null check (kind in ('call', 'visit', 'message', 'meeting', 'task')),
  due_at timestamptz,
  done_at timestamptz,
  owner_user_id uuid references kernel.app_user(id),
  note text
);
comment on table crm.activity is 'Calls, visits and follow-ups.';
create index activity_ix1 on crm.activity (related_type, related_id);
create index activity_ix2 on crm.activity (owner_user_id, due_at);
alter table crm.activity enable row level security;
alter table crm.activity force row level security;
create policy tenant_isolation on crm.activity
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

