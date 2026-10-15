-- Ziira Core 1.0 · schema 'connect' (Connectors / standalone mode) · install migration
-- Requires: kernel
-- A connection to another system (an ERP, a POS, a bank or mobile-money statement), what was read from it, and the
-- read-only canonical copy (src_*) that Intelligence's standalone checks look at. Nothing here is ever written back to
-- the source system. Secrets live in kernel.integration_credential (encrypted), never in these tables.

create schema if not exists connect;

create table connect.connection (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  kind text not null,
  name text not null,
  status text not null default 'active' check (status in ('active', 'paused', 'error', 'disconnected')),
  config jsonb not null default '{}',
  credential_id uuid references kernel.integration_credential(id),
  auto_create_branches boolean not null default false,
  sync_every_minutes integer not null default 1440 check (sync_every_minutes >= 15),
  last_sync_at timestamptz,
  last_success_at timestamptz,
  next_sync_at timestamptz,
  failures integer not null default 0,
  last_error text,
  disconnected_at timestamptz,
  unique (tenant_id, company_id, name)
);
comment on table connect.connection is 'A connected system. Non-secret settings in config; the secret is the credential.';
comment on column connect.connection.config is 'Non-secret settings only (URL, database, column mapping). Never a password or key.';
comment on column connect.connection.sync_every_minutes is 'The freshness window: how often the system is read (API kinds).';
create index connection_ix1 on connect.connection (tenant_id, company_id, status);
create index connection_ix2 on connect.connection (status, next_sync_at);
alter table connect.connection enable row level security;
alter table connect.connection force row level security;
create policy tenant_isolation on connect.connection
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.sync_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  entity text not null,
  trigger text not null default 'schedule' check (trigger in ('schedule', 'manual', 'upload', 'cli')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'ok', 'partial', 'failed')),
  records_read integer not null default 0,
  records_new integer not null default 0,
  records_changed integer not null default 0,
  records_skipped integer not null default 0,
  error text,
  notes jsonb not null default '[]'
);
comment on table connect.sync_run is 'One read of one entity from a connection: what was read and what became of it.';
create index sync_run_ix1 on connect.sync_run (tenant_id, connection_id, started_at desc);
alter table connect.sync_run enable row level security;
alter table connect.sync_run force row level security;
create policy tenant_isolation on connect.sync_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.cursor (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  entity text not null,
  cursor text,
  data_through timestamptz,
  updated_at timestamptz not null default now(),
  unique (connection_id, entity)
);
comment on table connect.cursor is 'Where the last COMPLETE read of an entity ended. A row exists once the entity was fully read.';
comment on column connect.cursor.data_through is 'The moment up to which the data is complete (checks judge only days that ended before it).';
alter table connect.cursor enable row level security;
alter table connect.cursor force row level security;
create policy tenant_isolation on connect.cursor
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.branch_map (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  external_ref text not null,
  external_name text,
  branch_id uuid references kernel.branch(id),
  ignored boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (connection_id, external_ref),
  check (not (ignored and branch_id is not null))
);
comment on table connect.branch_map is 'Which Ziira branch a branch (or till, store, warehouse) of the other system is. Unmapped: company level.';
alter table connect.branch_map enable row level security;
alter table connect.branch_map force row level security;
create policy tenant_isolation on connect.branch_map
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_branch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  name text not null,
  unique (connection_id, ref)
);
comment on table connect.src_branch is 'A branch, store or till of the source system.';
alter table connect.src_branch enable row level security;
alter table connect.src_branch force row level security;
create policy tenant_isolation on connect.src_branch
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_party (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  kind text not null check (kind in ('customer', 'supplier')),
  name text not null,
  phone text,
  email text,
  tax_id text,
  source_created_at timestamptz,
  erased boolean not null default false,
  unique (connection_id, ref)
);
comment on table connect.src_party is 'A customer or supplier of the source system (personal data: see the privacy provider).';
create index src_party_ix1 on connect.src_party (tenant_id, company_id, kind);
alter table connect.src_party enable row level security;
alter table connect.src_party force row level security;
create policy tenant_isolation on connect.src_party
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_product (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  name text not null,
  sku text,
  category text,
  unit_cost numeric(20,4),
  unit_price numeric(20,4),
  unique (connection_id, ref)
);
comment on table connect.src_product is 'A product of the source system.';
create index src_product_ix1 on connect.src_product (tenant_id, connection_id, name);
alter table connect.src_product enable row level security;
alter table connect.src_product force row level security;
create policy tenant_isolation on connect.src_product
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_user (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  name text not null,
  role text,
  email text,
  source_created_at timestamptz,
  erased boolean not null default false,
  unique (connection_id, ref)
);
comment on table connect.src_user is 'A user (cashier, clerk) of the source system (personal data).';
create index src_user_ix1 on connect.src_user (tenant_id, company_id);
alter table connect.src_user enable row level security;
alter table connect.src_user force row level security;
create policy tenant_isolation on connect.src_user
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_sale (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  occurred_at timestamptz not null,
  entered_at timestamptz,
  total numeric(20,4) not null,
  status text not null default 'posted' check (status in ('posted', 'voided', 'refunded')),
  number text,
  branch_ref text,
  branch_id uuid references kernel.branch(id),
  cashier_ref text,
  customer_ref text,
  tax_total numeric(20,4) not null default 0,
  discount_total numeric(20,4) not null default 0,
  currency text,
  voided_by_ref text,
  unique (connection_id, ref)
);
comment on table connect.src_sale is 'A sale (receipt, invoice-at-till) of the source system.';
create index src_sale_ix1 on connect.src_sale (tenant_id, company_id, occurred_at);
create index src_sale_ix2 on connect.src_sale (tenant_id, connection_id, cashier_ref, occurred_at);
create index src_sale_ix3 on connect.src_sale (tenant_id, branch_id, occurred_at);
alter table connect.src_sale enable row level security;
alter table connect.src_sale force row level security;
create policy tenant_isolation on connect.src_sale
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_sale_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  sale_id uuid not null references connect.src_sale(id) on delete cascade,
  connection_id uuid not null references connect.connection(id) on delete cascade,
  line_no integer not null,
  product_ref text,
  quantity numeric(20,4) not null,
  unit_price numeric(20,4) not null,
  discount numeric(20,4) not null default 0,
  list_price numeric(20,4),
  unique (sale_id, line_no)
);
create index src_sale_line_ix1 on connect.src_sale_line (tenant_id, sale_id);
alter table connect.src_sale_line enable row level security;
alter table connect.src_sale_line force row level security;
create policy tenant_isolation on connect.src_sale_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_sale_payment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  sale_id uuid not null references connect.src_sale(id) on delete cascade,
  connection_id uuid not null references connect.connection(id) on delete cascade,
  line_no integer not null,
  method text not null,
  amount numeric(20,4) not null,
  reference text,
  unique (sale_id, line_no)
);
create index src_sale_payment_ix1 on connect.src_sale_payment (tenant_id, sale_id);
create index src_sale_payment_ix2 on connect.src_sale_payment (tenant_id, method, amount);
alter table connect.src_sale_payment enable row level security;
alter table connect.src_sale_payment force row level security;
create policy tenant_isolation on connect.src_sale_payment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_payment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  occurred_at timestamptz not null,
  direction text not null check (direction in ('in', 'out')),
  amount numeric(20,4) not null,
  method text not null default 'other',
  reference text,
  party_ref text,
  party_name text,
  account text,
  branch_ref text,
  branch_id uuid references kernel.branch(id),
  invoice_ref text,
  currency text,
  unique (connection_id, ref)
);
comment on table connect.src_payment is 'Money in or out that the source or a statement shows: the evidence sales are checked against.';
create index src_payment_ix1 on connect.src_payment (tenant_id, company_id, direction, occurred_at);
create index src_payment_ix2 on connect.src_payment (tenant_id, company_id, lower(reference));
alter table connect.src_payment enable row level security;
alter table connect.src_payment force row level security;
create policy tenant_isolation on connect.src_payment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_stock_movement (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  occurred_at timestamptz not null,
  product_ref text not null,
  quantity numeric(20,4) not null,
  kind text not null default 'other',
  branch_ref text,
  branch_id uuid references kernel.branch(id),
  user_ref text,
  reason text,
  unit_cost numeric(20,4),
  entered_at timestamptz,
  unique (connection_id, ref)
);
comment on table connect.src_stock_movement is 'A stock movement of the source system (+ in, - out).';
create index src_stock_movement_ix1 on connect.src_stock_movement (tenant_id, company_id, kind, occurred_at);
create index src_stock_movement_ix2 on connect.src_stock_movement (tenant_id, connection_id, product_ref);
alter table connect.src_stock_movement enable row level security;
alter table connect.src_stock_movement force row level security;
create policy tenant_isolation on connect.src_stock_movement
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_invoice (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  kind text not null check (kind in ('customer', 'supplier')),
  issue_date date not null,
  due_date date,
  total numeric(20,4) not null,
  paid numeric(20,4) not null default 0,
  number text,
  party_ref text,
  branch_ref text,
  branch_id uuid references kernel.branch(id),
  status text not null default 'open' check (status in ('open', 'paid', 'cancelled', 'draft')),
  created_by_ref text,
  approved_by_ref text,
  currency text,
  unique (connection_id, ref)
);
comment on table connect.src_invoice is 'A customer or supplier invoice of the source system.';
create index src_invoice_ix1 on connect.src_invoice (tenant_id, company_id, kind, status, due_date);
create index src_invoice_ix2 on connect.src_invoice (tenant_id, connection_id, party_ref);
alter table connect.src_invoice enable row level security;
alter table connect.src_invoice force row level security;
create policy tenant_isolation on connect.src_invoice
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_expense (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  occurred_at timestamptz not null,
  amount numeric(20,4) not null,
  category text,
  description text,
  branch_ref text,
  branch_id uuid references kernel.branch(id),
  user_ref text,
  party_ref text,
  unique (connection_id, ref)
);
comment on table connect.src_expense is 'An expense of the source system.';
create index src_expense_ix1 on connect.src_expense (tenant_id, company_id, occurred_at);
alter table connect.src_expense enable row level security;
alter table connect.src_expense force row level security;
create policy tenant_isolation on connect.src_expense
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_journal_entry (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  ref text not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  entry_date date not null,
  number text,
  entered_at timestamptz,
  created_by_ref text,
  approved_by_ref text,
  memo text,
  is_manual boolean not null default true,
  total_debit numeric(20,4) not null default 0,
  unique (connection_id, ref)
);
comment on table connect.src_journal_entry is 'A journal entry of the source system''s books.';
create index src_journal_entry_ix1 on connect.src_journal_entry (tenant_id, company_id, entry_date);
alter table connect.src_journal_entry enable row level security;
alter table connect.src_journal_entry force row level security;
create policy tenant_isolation on connect.src_journal_entry
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.src_journal_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  entry_id uuid not null references connect.src_journal_entry(id) on delete cascade,
  connection_id uuid not null references connect.connection(id) on delete cascade,
  line_no integer not null,
  account text not null,
  debit numeric(20,4) not null default 0,
  credit numeric(20,4) not null default 0,
  party_ref text,
  unique (entry_id, line_no)
);
create index src_journal_line_ix1 on connect.src_journal_line (tenant_id, entry_id);
alter table connect.src_journal_line enable row level security;
alter table connect.src_journal_line force row level security;
create policy tenant_isolation on connect.src_journal_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
