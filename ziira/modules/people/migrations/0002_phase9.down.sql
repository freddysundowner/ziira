drop index if exists people.payslip_employee;
alter table people.payslip_line drop column if exists description;
alter table people.payslip drop column if exists pay_method, drop column if exists detail, drop column if exists benefits,
  drop column if exists branch_id;
alter table people.payroll_run drop constraint if exists payroll_run_period_check;
drop index if exists people.payroll_run_one_per_period;
alter table people.payroll_run add constraint payroll_run_company_id_period_start_key unique (company_id, period_start);
alter table people.payroll_run drop column if exists unpaid_day_divisor, drop column if exists reject_note,
  drop column if exists paid_by, drop column if exists paid_at, drop column if exists approved_at,
  drop column if exists submitted_at, drop column if exists exceptions;
alter table people.attendance drop constraint if exists attendance_hours_check;
drop index if exists people.attendance_one_per_day;
alter table people.leave_request drop column if exists decided_note, drop column if exists reason;
alter table people.employee_pay_item drop column if exists description;
alter table people.employee_bank_account drop column if exists rejected;
alter table people.employee_bank_account drop constraint if exists employee_bank_account_method_check;
alter table people.employee_bank_account add constraint employee_bank_account_method_check check (method in ('bank', 'mpesa'));
alter table people.employment_terms drop column if exists rejected, drop column if exists note;
drop index if exists people.shift_unique;
alter table people.shift drop column if exists company_id;
alter table people.leave_type drop constraint if exists leave_type_unique;
alter table people.employee drop column if exists is_director, drop column if exists residency,
  drop column if exists exempt_rules, drop column if exists registrations;
alter table people.employee add column nssf_no text, add column shif_no text;
alter table people.employee rename column tax_id to kra_pin;
drop policy if exists tenant_isolation on people.statutory_rate_table;
alter table people.statutory_rate_table disable row level security;
alter table people.statutory_rate_table drop constraint if exists statutory_rate_table_unique;
alter table people.statutory_rate_table drop constraint if exists statutory_rate_table_code_format;
alter table people.statutory_rate_table drop column if exists is_verified, drop column if exists payable_account_id,
  drop column if exists created_by, drop column if exists created_at, drop column if exists company_id,
  drop column if exists tenant_id;
