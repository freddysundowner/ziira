-- Ziira Core · schema 'jobs' (Jobs and Repairs) · install migration
-- Requires: kernel, products
-- Work orders, the things customers leave (assets), the stages a job moves through (data, per company), tasks, parts,
-- labour, estimates and the customer's answer. Customers (crm), stock locations (inventory) and invoices (pos) are
-- plain ids: those units are optional.

create schema if not exists jobs;

create table jobs.setting (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id) unique,
  default_labour_rate numeric(18,2) not null default 0 check (default_labour_rate >= 0),
  labour_product_id uuid references products.product(id),
  parts_product_id uuid references products.product(id),
  estimate_valid_days integer not null default 14 check (estimate_valid_days between 1 and 365),
  default_warranty_days integer not null default 0 check (default_warranty_days between 0 and 3650),
  tell_customer_when_ready boolean not null default true
);
comment on table jobs.setting is 'Per-company job settings. Labour and parts are invoiced under these two service items, so their tax codes decide the tax.';
alter table jobs.setting enable row level security;
alter table jobs.setting force row level security;
create policy tenant_isolation on jobs.setting
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table jobs.job_status (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  kind text not null check (kind in ('open', 'waiting', 'done', 'closed')),
  role text check (role in ('initial', 'quoted', 'approved', 'ready', 'collected', 'closed', 'cancelled')),
  position integer not null default 0,
  is_active boolean not null default true,
  unique (company_id, code),
  unique (company_id, role)
);
comment on table jobs.job_status is 'A stage a job can be in (data, so a business or an industry pack can have its own).';
alter table jobs.job_status enable row level security;
alter table jobs.job_status force row level security;
create policy tenant_isolation on jobs.job_status
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table jobs.job_status_move (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  from_status_id uuid not null references jobs.job_status(id),
  to_status_id uuid not null references jobs.job_status(id),
  unique (from_status_id, to_status_id),
  check (from_status_id <> to_status_id)
);
comment on table jobs.job_status_move is 'A move between two stages that is allowed.';
alter table jobs.job_status_move enable row level security;
alter table jobs.job_status_move force row level security;
create policy tenant_isolation on jobs.job_status_move
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table jobs.checklist_template (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  asset_kind text,
  items jsonb not null default '[]',
  is_active boolean not null default true,
  unique (company_id, name)
);
comment on table jobs.checklist_template is 'The intake checklist a new job copies.';
alter table jobs.checklist_template enable row level security;
alter table jobs.checklist_template force row level security;
create policy tenant_isolation on jobs.checklist_template
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table jobs.asset (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid,
  kind text not null default 'item',
  label text not null,
  identifiers jsonb not null default '{}',
  notes text,
  is_active boolean not null default true
);
comment on table jobs.asset is 'A vehicle, device, garment or place a customer brings (free identifiers: plate, serial, IMEI, size, address).';
alter table jobs.asset enable row level security;
alter table jobs.asset force row level security;
create policy tenant_isolation on jobs.asset
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index asset_ix1 on jobs.asset (company_id, customer_id);

create table jobs.job (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  customer_id uuid,
  customer_name text,
  customer_phone text,
  asset_id uuid references jobs.asset(id),
  status_id uuid not null references jobs.job_status(id),
  status_changed_at timestamptz not null default now(),
  title text not null,
  description text,
  condition_notes text,
  assignee_id uuid references kernel.app_user(id),
  received_at timestamptz not null default now(),
  promised_at date,
  estimate_sent_at timestamptz,
  ready_at timestamptz,
  collected_at timestamptz,
  collected_by_name text,
  closed_at timestamptz,
  warranty_days integer not null default 0 check (warranty_days between 0 and 3650),
  warranty_ends date,
  is_rework boolean not null default false,
  rework_of_id uuid references jobs.job(id),
  rework_in_warranty boolean,
  invoice_id uuid,
  invoice_number text,
  invoiced_at timestamptz,
  unique (company_id, number)
);
comment on table jobs.job is 'A work order.';
alter table jobs.job enable row level security;
alter table jobs.job force row level security;
create policy tenant_isolation on jobs.job
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index job_ix1 on jobs.job (company_id, status_id);
create index job_ix2 on jobs.job (asset_id);
create index job_ix3 on jobs.job (company_id, customer_id);
create index job_ix4 on jobs.job (assignee_id);
create index job_ix5 on jobs.job (rework_of_id);

create table jobs.job_checklist_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  job_id uuid not null references jobs.job(id),
  position integer not null,
  label text not null,
  state text not null default 'pending' check (state in ('pending', 'ok', 'issue', 'na')),
  note text
);
alter table jobs.job_checklist_item enable row level security;
alter table jobs.job_checklist_item force row level security;
create policy tenant_isolation on jobs.job_checklist_item
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index job_checklist_item_ix1 on jobs.job_checklist_item (job_id, position);

create table jobs.job_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  job_id uuid not null references jobs.job(id),
  kind text not null check (kind in ('received', 'status', 'note', 'assigned', 'estimate', 'approval', 'parts', 'labour',
                                     'invoice', 'collected', 'rework', 'warranty')),
  from_status_id uuid references jobs.job_status(id),
  to_status_id uuid references jobs.job_status(id),
  note text,
  created_by uuid references kernel.app_user(id)
);
comment on table jobs.job_event is 'The timeline of a job: status changes, notes and what was done.';
alter table jobs.job_event enable row level security;
alter table jobs.job_event force row level security;
create policy tenant_isolation on jobs.job_event
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index job_event_ix1 on jobs.job_event (job_id, created_at);

create table jobs.job_task (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  title text not null,
  assignee_id uuid references kernel.app_user(id),
  due_date date,
  done_at timestamptz,
  done_by uuid references kernel.app_user(id),
  position integer not null default 0
);
alter table jobs.job_task enable row level security;
alter table jobs.job_task force row level security;
create policy tenant_isolation on jobs.job_task
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index job_task_ix1 on jobs.job_task (job_id);
create index job_task_ix2 on jobs.job_task (assignee_id) where done_at is null;

create table jobs.job_part (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  product_id uuid references products.product(id),
  description text not null,
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,4) not null check (unit_price >= 0),
  tax_code_id uuid references products.tax_code(id),
  location_id uuid,
  is_stock boolean not null default false,
  unit_cost numeric(18,6),
  cost_value numeric(18,2),
  voided_at timestamptz,
  voided_by uuid references kernel.app_user(id)
);
comment on table jobs.job_part is 'A part used on a job: stock issued from a location, or something bought in and priced by hand.';
alter table jobs.job_part enable row level security;
alter table jobs.job_part force row level security;
create policy tenant_isolation on jobs.job_part
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index job_part_ix1 on jobs.job_part (job_id);

create table jobs.job_labour (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  description text not null,
  hours numeric(18,4) not null check (hours > 0),
  rate numeric(18,2) not null check (rate >= 0),
  assignee_id uuid references kernel.app_user(id),
  work_date date not null,
  source text not null default 'manual',
  source_id uuid,
  voided_at timestamptz,
  voided_by uuid references kernel.app_user(id)
);
comment on table jobs.job_labour is 'Labour on a job: hours x rate. `source` says where the line came from (manual now; timers later).';
alter table jobs.job_labour enable row level security;
alter table jobs.job_labour force row level security;
create policy tenant_isolation on jobs.job_labour
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index job_labour_ix1 on jobs.job_labour (job_id);

create table jobs.estimate (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  job_id uuid not null references jobs.job(id),
  version integer not null,
  status text not null default 'draft' check (status in ('draft', 'sent', 'approved', 'declined', 'superseded')),
  notes text,
  valid_until date,
  net numeric(18,2) not null default 0,
  tax numeric(18,2) not null default 0,
  total numeric(18,2) not null default 0,
  sent_at timestamptz,
  decided_at timestamptz,
  decided_by uuid references kernel.app_user(id),
  decided_by_name text,
  decision_channel text check (decision_channel in ('staff', 'link')),
  decision_note text,
  link_hash text,
  unique (job_id, version)
);
comment on table jobs.estimate is 'A priced offer for a job; each change after sending is a new version.';
alter table jobs.estimate enable row level security;
alter table jobs.estimate force row level security;
create policy tenant_isolation on jobs.estimate
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create unique index estimate_link_ix on jobs.estimate (link_hash) where link_hash is not null;

create table jobs.estimate_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  estimate_id uuid not null references jobs.estimate(id),
  position integer not null default 0,
  kind text not null check (kind in ('part', 'labour', 'other')),
  product_id uuid references products.product(id),
  description text not null,
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,4) not null check (unit_price >= 0),
  tax_code_id uuid references products.tax_code(id),
  net numeric(18,2) not null,
  tax numeric(18,2) not null
);
alter table jobs.estimate_line enable row level security;
alter table jobs.estimate_line force row level security;
create policy tenant_isolation on jobs.estimate_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index estimate_line_ix1 on jobs.estimate_line (estimate_id, position);
