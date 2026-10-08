-- Ziira Core 1.0 · schema 'people' (People, HR and Payroll) · install migration
-- Requires: kernel
-- Employees, attendance, leave and payroll.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists people;

create table people.department (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  unique (company_id, name)
);
comment on table people.department is 'Departments.';
alter table people.department enable row level security;
alter table people.department force row level security;
create policy tenant_isolation on people.department
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.employee (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  department_id uuid references people.department(id),
  user_id uuid references kernel.app_user(id),
  employee_no text not null,
  full_name text not null,
  national_id_ciphertext bytea,
  kra_pin text,
  nssf_no text,
  shif_no text,
  phone text,
  email text,
  hire_date date not null,
  termination_date date,
  status text not null default 'active' check (status in ('active', 'on_leave', 'terminated')),
  unique (company_id, employee_no)
);
comment on table people.employee is 'An employee.';
comment on column people.employee.user_id is 'Link to the POS or system user';
comment on column people.employee.national_id_ciphertext is 'Encrypted';
alter table people.employee enable row level security;
alter table people.employee force row level security;
create policy tenant_isolation on people.employee
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.pay_component (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  kind text not null check (kind in ('earning', 'deduction', 'benefit', 'employer_contribution')),
  is_taxable boolean not null default true,
  is_statutory boolean not null default false,
  statutory_code text,
  unique (company_id, code)
);
comment on table people.pay_component is 'Earnings, deductions and benefits.';
comment on column people.pay_component.statutory_code is 'Links to statutory_rate_table.code';
alter table people.pay_component enable row level security;
alter table people.pay_component force row level security;
create policy tenant_isolation on people.pay_component
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.employment_terms (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  employee_id uuid not null references people.employee(id),
  basic_pay numeric(18,2) not null check (basic_pay >= 0),
  pay_frequency text not null default 'monthly' check (pay_frequency in ('monthly')),
  valid_from date not null,
  valid_to date,
  approved_by uuid references kernel.app_user(id)
);
comment on table people.employment_terms is 'Basic pay and terms (versioned).';
create index employment_terms_ix1 on people.employment_terms (employee_id, valid_from);
alter table people.employment_terms enable row level security;
alter table people.employment_terms force row level security;
create policy tenant_isolation on people.employment_terms
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.employee_pay_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  employee_id uuid not null references people.employee(id),
  component_id uuid not null references people.pay_component(id),
  amount numeric(18,2) not null,
  recurring boolean not null default true,
  valid_from date not null,
  valid_to date
);
comment on table people.employee_pay_item is 'Recurring or one-off pay items.';
alter table people.employee_pay_item enable row level security;
alter table people.employee_pay_item force row level security;
create policy tenant_isolation on people.employee_pay_item
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.employee_bank_account (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  employee_id uuid not null references people.employee(id),
  method text not null check (method in ('bank', 'mpesa')),
  bank_name text,
  account_no_ciphertext bytea,
  account_no_masked text,
  valid_from timestamptz not null,
  valid_to timestamptz,
  approved_by uuid references kernel.app_user(id)
);
comment on table people.employee_bank_account is 'Salary payment details (versioned; changes approved).';
alter table people.employee_bank_account enable row level security;
alter table people.employee_bank_account force row level security;
create policy tenant_isolation on people.employee_bank_account
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.shift (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  branch_id uuid references kernel.branch(id),
  name text not null,
  start_time time not null,
  end_time time not null
);
comment on table people.shift is 'Shift definitions.';
alter table people.shift enable row level security;
alter table people.shift force row level security;
create policy tenant_isolation on people.shift
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.attendance (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  employee_id uuid not null references people.employee(id),
  branch_id uuid references kernel.branch(id),
  work_date date not null,
  shift_id uuid references people.shift(id),
  clock_in timestamptz,
  clock_out timestamptz,
  hours numeric(6,2),
  overtime_hours numeric(6,2) not null default 0,
  source text not null check (source in ('pos_login', 'device', 'manual')),
  unique (employee_id, work_date, shift_id)
);
comment on table people.attendance is 'Daily attendance.';
alter table people.attendance enable row level security;
alter table people.attendance force row level security;
create policy tenant_isolation on people.attendance
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.leave_type (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  days_per_year numeric(6,2),
  is_paid boolean not null default true
);
comment on table people.leave_type is 'Types of leave.';
alter table people.leave_type enable row level security;
alter table people.leave_type force row level security;
create policy tenant_isolation on people.leave_type
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.leave_request (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  employee_id uuid not null references people.employee(id),
  leave_type_id uuid not null references people.leave_type(id),
  start_date date not null,
  end_date date not null,
  days numeric(6,2) not null,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'cancelled')),
  approved_by uuid references kernel.app_user(id),
  check (end_date >= start_date)
);
comment on table people.leave_request is 'A request for leave.';
alter table people.leave_request enable row level security;
alter table people.leave_request force row level security;
create policy tenant_isolation on people.leave_request
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.statutory_rate_table (
  id uuid primary key default gen_random_uuid(),
  code text not null check (code in ('paye', 'shif', 'nssf', 'housing_levy', 'other')),
  effective_from date not null,
  effective_to date,
  definition jsonb not null,
  source_reference text not null,
  verified_by text not null,
  verified_at timestamptz not null,
  unique (code, effective_from)
);
comment on table people.statutory_rate_table is 'Effective-dated statutory rules (platform level).';
comment on column people.statutory_rate_table.definition is 'Bands, rates, limits, reliefs, calculation order';
comment on column people.statutory_rate_table.source_reference is 'Law or notice the values come from';

create table people.payroll_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  period_start date not null,
  period_end date not null,
  pay_date date not null,
  status text not null default 'draft' check (status in ('draft', 'calculated', 'pending_approval', 'approved', 'posted', 'paid', 'cancelled')),
  totals jsonb not null default '{}',
  prepared_by uuid references kernel.app_user(id),
  approved_by uuid references kernel.app_user(id),
  journal_entry_id uuid,
  unique (company_id, period_start),
  check (approved_by is null or approved_by <> prepared_by)
);
comment on table people.payroll_run is 'A monthly payroll run.';
comment on column people.payroll_run.journal_entry_id is 'Soft reference to finance.journal_entry';
alter table people.payroll_run enable row level security;
alter table people.payroll_run force row level security;
create policy tenant_isolation on people.payroll_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.payslip (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  run_id uuid not null references people.payroll_run(id),
  employee_id uuid not null references people.employee(id),
  gross_pay numeric(18,2) not null,
  taxable_pay numeric(18,2) not null,
  total_deductions numeric(18,2) not null,
  net_pay numeric(18,2) not null,
  employer_cost numeric(18,2) not null,
  file_id uuid references kernel.file(id),
  status text not null default 'calculated' check (status in ('calculated', 'approved', 'paid')),
  unique (run_id, employee_id)
);
comment on table people.payslip is 'One employee''s result in a run.';
alter table people.payslip enable row level security;
alter table people.payslip force row level security;
create policy tenant_isolation on people.payslip
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table people.payslip_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  payslip_id uuid not null references people.payslip(id),
  component_code text not null,
  kind text not null check (kind in ('earning', 'deduction', 'benefit', 'employer_contribution')),
  amount numeric(18,2) not null,
  rate_table_id uuid references people.statutory_rate_table(id)
);
comment on table people.payslip_line is 'Each earning and deduction on a payslip.';
comment on column people.payslip_line.rate_table_id is 'Which rule version produced it';
alter table people.payslip_line enable row level security;
alter table people.payslip_line force row level security;
create policy tenant_isolation on people.payslip_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

