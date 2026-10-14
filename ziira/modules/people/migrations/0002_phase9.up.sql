-- Phase 9: statutory rate tables held per business (and verified by a person), approvals for pay and bank changes,
-- payroll runs with review exceptions, payslip detail for P9 and returns.

-- Statutory rules: taxes, contributions and levies are defined by each business as data (see domain/rules.py), with an
-- effective date, and checked by a person before a run that used them can be approved. No country's rules live in code.
alter table people.statutory_rate_table drop constraint statutory_rate_table_code_check;
alter table people.statutory_rate_table drop constraint statutory_rate_table_code_effective_from_key;
alter table people.statutory_rate_table
  add column tenant_id uuid references kernel.tenant(id),
  add column company_id uuid references kernel.company(id),
  add column created_at timestamptz not null default now(),
  add column created_by uuid references kernel.app_user(id),
  add column payable_account_id uuid,
  add column is_verified boolean not null default false,
  alter column verified_by drop not null,
  alter column verified_at drop not null;
alter table people.statutory_rate_table alter column tenant_id set not null;
alter table people.statutory_rate_table alter column company_id set not null;
alter table people.statutory_rate_table add constraint statutory_rate_table_code_format
  check (code ~ '^[A-Z][A-Z0-9_]{0,19}$');
alter table people.statutory_rate_table add constraint statutory_rate_table_unique
  unique (company_id, code, effective_from);
alter table people.statutory_rate_table enable row level security;
alter table people.statutory_rate_table force row level security;
create policy tenant_isolation on people.statutory_rate_table
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
comment on column people.statutory_rate_table.code is 'The business''s own code for the rule (PAYE, PENSION, ...)';
comment on column people.statutory_rate_table.payable_account_id is 'Soft reference to the finance account the amount is owed through';
comment on column people.statutory_rate_table.is_verified is 'True once a person has checked the values against the official notice';

-- Employees
alter table people.employee rename column kra_pin to tax_id;
alter table people.employee
  drop column nssf_no,
  drop column shif_no,
  add column registrations jsonb not null default '{}',
  add column exempt_rules text[] not null default '{}',
  add column residency text not null default 'resident' check (residency in ('resident', 'non_resident')),
  add column is_director boolean not null default false;
comment on column people.employee.tax_id is 'The employee''s tax number';
comment on column people.employee.registrations is 'Numbers with the bodies that collect contributions, by rule code';
alter table people.employee_bank_account drop constraint employee_bank_account_method_check;
alter table people.employee_bank_account add constraint employee_bank_account_method_check
  check (method in ('bank', 'mobile_money'));
alter table people.leave_type add constraint leave_type_unique unique (company_id, name);
create unique index shift_unique on people.shift (coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

-- A pay or bank detail change waits for a different person to approve it (approved_by is null until then).
alter table people.employment_terms add column note text, add column rejected boolean not null default false;
alter table people.employee_bank_account add column rejected boolean not null default false;
alter table people.employee_pay_item add column description text;
alter table people.leave_request
  add column reason text,
  add column decided_note text;
alter table people.attendance add constraint attendance_hours_check check (hours is null or (hours >= 0 and hours <= 24));

-- Payroll runs
alter table people.payroll_run
  add column exceptions jsonb not null default '[]',
  add column submitted_at timestamptz,
  add column approved_at timestamptz,
  add column paid_at timestamptz,
  add column paid_by uuid references kernel.app_user(id),
  add column reject_note text,
  add column unpaid_day_divisor smallint not null default 30,
  add constraint payroll_run_period_check check (period_end >= period_start);
alter table people.payslip
  add column branch_id uuid references kernel.branch(id),
  add column benefits numeric(18,2) not null default 0,
  add column detail jsonb not null default '{}',
  add column pay_method text check (pay_method in ('bank', 'mobile_money'));
alter table people.payslip_line add column description text;
create index payslip_employee on people.payslip (employee_id);
