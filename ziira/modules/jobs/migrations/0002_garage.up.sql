-- Ziira Core · schema 'jobs' · 0002 · garages, body shops and repair shops
-- Odometer and service reminders, intake details, work types and a task library, part classes and markups, special-order
-- parts, extra charges (towing, storage), additional-work estimates, bays and a bay board, courtesy-car loans, job types.

-- ------------------------------------------------------------------------------------------------ settings
alter table jobs.setting
  add column odometer_unit text not null default 'km' check (odometer_unit in ('km', 'mi')),
  add column unapproved_work text not null default 'warn' check (unapproved_work in ('off', 'warn', 'block')),
  add column release_unpaid text not null default 'off' check (release_unpaid in ('off', 'warn', 'block')),
  add column fees_product_id uuid references products.product(id),
  add column storage_fee_per_day numeric(18,2) not null default 0 check (storage_fee_per_day >= 0),
  add column storage_grace_days integer not null default 7 check (storage_grace_days between 0 and 365),
  add column remind_service_due boolean not null default false,
  add column service_reminder_days integer not null default 14 check (service_reminder_days between 1 and 120),
  add column ready_reminder_days integer not null default 0 check (ready_reminder_days between 0 and 60);
comment on column jobs.setting.unapproved_work is 'What happens when work is added beyond what the customer approved: off, warn or block.';
comment on column jobs.setting.release_unpaid is 'What happens when an item is handed over before the invoice is paid: off, warn or block.';

-- ------------------------------------------------------------------------------------------------ the item (vehicle, device)
alter table jobs.asset
  add column odometer numeric(12,1) check (odometer is null or odometer >= 0),
  add column odometer_at timestamptz,
  add column next_service_date date,
  add column next_service_odometer numeric(12,1) check (next_service_odometer is null or next_service_odometer >= 0),
  add column next_service_note text,
  add column service_reminded_for date;
comment on column jobs.asset.odometer is 'The last reading seen on a visit (the job carries each visit''s own).';
comment on column jobs.asset.service_reminded_for is 'The next-service date a reminder was already queued for.';

-- ------------------------------------------------------------------------------------------------ job types (data)
create table jobs.job_type (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  checklist_template_id uuid references jobs.checklist_template(id) on delete set null,
  default_warranty_days integer check (default_warranty_days is null or default_warranty_days between 0 and 3650),
  position integer not null default 0,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table jobs.job_type is 'A kind of job a business does (service, body repair, alteration): its own checklist and warranty.';

alter table jobs.job
  add column job_type_code text,
  add column odometer_in numeric(12,1) check (odometer_in is null or odometer_in >= 0),
  add column odometer_out numeric(12,1) check (odometer_out is null or odometer_out >= 0),
  add column fuel_level text,
  add column key_tag text,
  add column belongings text,
  add column acknowledged_by_name text,
  add column acknowledged_at timestamptz,
  add column deposit_amount numeric(18,2) check (deposit_amount is null or deposit_amount > 0),
  add column deposit_payment_id uuid,
  add column deposit_at timestamptz,
  add column deposit_note text,
  add column claim_id uuid,
  add column storage_fee_waived boolean not null default false;
comment on column jobs.job.claim_id is 'The insurance (or other payer) claim this job belongs to; a plain id into the claims unit.';

alter table jobs.job_event drop constraint if exists job_event_kind_check;
alter table jobs.job_event add constraint job_event_kind_check check (kind in (
  'received', 'status', 'note', 'assigned', 'estimate', 'approval', 'parts', 'labour', 'invoice', 'collected',
  'rework', 'warranty', 'charge', 'bay', 'loan', 'deposit', 'release', 'photo', 'claim', 'intake'));

-- ------------------------------------------------------------------------------------------------ labour: work types and tasks
create table jobs.work_type (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  hourly_rate numeric(18,2) check (hourly_rate is null or hourly_rate >= 0),
  position integer not null default 0,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table jobs.work_type is 'A kind of labour (mechanical, body, paint, electrical) with its own hourly rate; blank: the company rate.';

create table jobs.labour_task (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  work_type_code text,
  standard_hours numeric(8,2) not null check (standard_hours > 0),
  flat_price numeric(18,2) check (flat_price is null or flat_price >= 0),
  asset_kind text,
  is_example boolean not null default false,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table jobs.labour_task is 'The flat-rate library: a standard job with a standard time (and optionally a fixed price).';

alter table jobs.job_labour
  add column work_type_code text,
  add column task_code text,
  add column booked_hours numeric(18,4) check (booked_hours is null or booked_hours >= 0),
  add column flat_price numeric(18,2) check (flat_price is null or flat_price >= 0);
comment on column jobs.job_labour.hours is 'Hours BILLED. booked_hours is the time the technician actually worked.';

-- ------------------------------------------------------------------------------------------------ parts
create table jobs.part_category (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  markup_percent numeric(7,2) not null default 0 check (markup_percent >= 0 and markup_percent <= 1000),
  default_class text check (default_class is null or default_class in ('genuine', 'aftermarket', 'used')),
  position integer not null default 0,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table jobs.part_category is 'A kind of part (tyres, oil, panels, electronics) with the markup on cost the business applies.';

alter table jobs.job_part
  add column part_class text check (part_class is null or part_class in ('genuine', 'aftermarket', 'used')),
  add column category_code text,
  add column source text not null default 'stock' check (source in ('stock', 'bought_in', 'special_order', 'customer_supplied')),
  add column order_status text check (order_status is null or order_status in ('to_order', 'ordered', 'arrived')),
  add column supplier_id uuid,
  add column supplier_name text,
  add column purchase_order_id uuid,
  add column purchase_order_number text,
  add column expected_on date,
  add column ordered_at timestamptz,
  add column arrived_at timestamptz,
  add column cost_price numeric(18,4) check (cost_price is null or cost_price >= 0),
  add column keep_old_part boolean not null default false,
  add column old_part_note text,
  add column void_reason text;
-- existing rows: bought-in or hand priced parts that are not stock
update jobs.job_part set source = 'bought_in' where not is_stock;

alter table jobs.estimate
  add column kind text not null default 'main' check (kind in ('main', 'additional'));
alter table jobs.estimate_line
  add column work_type_code text,
  add column part_class text check (part_class is null or part_class in ('genuine', 'aftermarket', 'used'));

-- ------------------------------------------------------------------------------------------------ extra charges (towing, storage ...)
create table jobs.job_charge (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  kind text not null check (kind in ('towing', 'storage', 'courtesy_car', 'other')),
  description text not null,
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,4) not null check (unit_price >= 0),
  tax_code_id uuid references products.tax_code(id),
  voided_at timestamptz,
  voided_by uuid references kernel.app_user(id)
);
comment on table jobs.job_charge is 'A charge that is neither a part nor labour: towing, courtesy car, an agreed fee. Invoiced under the fees item.';
create index job_charge_ix1 on jobs.job_charge (job_id);

-- ------------------------------------------------------------------------------------------------ bays and the bay board
create table jobs.bay (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  name text not null,
  position integer not null default 0,
  is_active boolean not null default true,
  unique (branch_id, name)
);
comment on table jobs.bay is 'A place in the workshop a job is worked on: a bay, a lift, a paint booth, a bench.';

create extension if not exists btree_gist;

create table jobs.bay_booking (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  bay_id uuid not null references jobs.bay(id),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  note text,
  cancelled_at timestamptz,
  cancelled_by uuid references kernel.app_user(id),
  check (ends_at > starts_at),
  constraint no_double_bay exclude using gist (bay_id with =, tstzrange(starts_at, ends_at) with &&)
    where (cancelled_at is null)
);
comment on table jobs.bay_booking is 'A job scheduled into a bay for a time. A bay cannot hold two jobs at once.';
create index bay_booking_ix1 on jobs.bay_booking (job_id);
create index bay_booking_ix2 on jobs.bay_booking (bay_id, starts_at);

-- ------------------------------------------------------------------------------------------------ courtesy / hire car loans
create table jobs.loan (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  asset_id uuid not null references jobs.asset(id),
  borrower_name text,
  out_at timestamptz not null default now(),
  due_at date,
  in_at timestamptz,
  odometer_out numeric(12,1),
  odometer_in numeric(12,1),
  fuel_out text,
  fuel_in text,
  note text
);
comment on table jobs.loan is 'A courtesy or hire car lent to a customer while theirs is in the workshop: out and in dates, nothing more.';
create unique index loan_one_out_ix on jobs.loan (asset_id) where in_at is null;
create index loan_ix1 on jobs.loan (job_id);

-- ------------------------------------------------------------------------------------------------ row level security for the new tables
do $$
declare t text;
begin
  foreach t in array array['job_type', 'work_type', 'labour_task', 'part_category', 'job_charge', 'bay', 'bay_booking', 'loan']
  loop
    execute format('alter table jobs.%I enable row level security', t);
    execute format('alter table jobs.%I force row level security', t);
    execute format('create policy tenant_isolation on jobs.%I using (tenant_id = kernel.current_tenant()) '
                   'with check (tenant_id = kernel.current_tenant())', t);
  end loop;
end $$;
