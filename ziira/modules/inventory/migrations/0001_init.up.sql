-- Ziira Core 1.0 · schema 'inventory' (Inventory and Branches) · install migration
-- Requires: kernel, products
-- Stock ledger, balances, costing, transfers and counts.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists inventory;

create table inventory.location (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  code text not null,
  name text not null,
  kind text not null default 'store' check (kind in ('store', 'warehouse', 'transit', 'virtual')),
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table inventory.location is 'A place stock is held.';
comment on column inventory.location.branch_id is 'Null for in-transit or virtual locations';
alter table inventory.location enable row level security;
alter table inventory.location force row level security;
create policy tenant_isolation on inventory.location
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.batch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  product_id uuid not null references products.product(id),
  batch_no text not null,
  expiry_date date,
  unique (product_id, batch_no)
);
comment on table inventory.batch is 'Lot with expiry for batch-tracked products.';
create index batch_ix1 on inventory.batch (tenant_id, expiry_date);
alter table inventory.batch enable row level security;
alter table inventory.batch force row level security;
create policy tenant_isolation on inventory.batch
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.stock_movement (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  location_id uuid not null references inventory.location(id),
  product_id uuid not null references products.product(id),
  batch_id uuid references inventory.batch(id),
  quantity numeric(18,4) not null check (quantity <> 0),
  unit_cost numeric(18,6) not null,
  value numeric(18,2) not null,
  movement_type text not null check (movement_type in ('sale', 'sale_return', 'receipt', 'purchase_return', 'transfer_out', 'transfer_in', 'adjustment', 'count_variance', 'write_off', 'opening')),
  source_type text not null,
  source_id uuid not null,
  source_line_id uuid,
  reason_code_id uuid references kernel.reason_code(id),
  business_date date not null,
  approved_by uuid references kernel.app_user(id),
  check (movement_type not in ('adjustment','count_variance','write_off') or reason_code_id is not null)
);
comment on table inventory.stock_movement is 'The stock ledger. Every quantity change; never updated.';
comment on column inventory.stock_movement.quantity is '+ in, - out, in base unit';
create index stock_movement_ix1 on inventory.stock_movement (location_id, product_id, business_date);
create index stock_movement_ix2 on inventory.stock_movement (source_type, source_id);
alter table inventory.stock_movement enable row level security;
alter table inventory.stock_movement force row level security;
create policy tenant_isolation on inventory.stock_movement
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger stock_movement_immutable before update or delete on inventory.stock_movement
  for each row execute function kernel.forbid_change();

create table inventory.stock_balance (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  location_id uuid not null references inventory.location(id),
  product_id uuid not null references products.product(id),
  batch_id uuid references inventory.batch(id),
  quantity numeric(18,4) not null default 0,
  updated_at timestamptz not null default now(),
  unique nulls not distinct (location_id, product_id, batch_id)
);
comment on table inventory.stock_balance is 'Current quantity per location, product and batch (derived).';
alter table inventory.stock_balance enable row level security;
alter table inventory.stock_balance force row level security;
create policy tenant_isolation on inventory.stock_balance
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.product_cost (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  product_id uuid not null references products.product(id),
  quantity numeric(18,4) not null default 0,
  value numeric(18,2) not null default 0,
  average_cost numeric(18,6) not null default 0,
  updated_at timestamptz not null default now(),
  unique (company_id, product_id)
);
comment on table inventory.product_cost is 'Weighted average cost per company and product (derived).';
alter table inventory.product_cost enable row level security;
alter table inventory.product_cost force row level security;
create policy tenant_isolation on inventory.product_cost
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.transfer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  number text not null,
  from_location_id uuid not null references inventory.location(id),
  to_location_id uuid not null references inventory.location(id),
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'dispatched', 'received', 'cancelled')),
  dispatched_at timestamptz,
  dispatched_by uuid references kernel.app_user(id),
  received_at timestamptz,
  received_by uuid references kernel.app_user(id),
  unique (company_id, number),
  check (from_location_id <> to_location_id)
);
comment on table inventory.transfer is 'Stock moved between locations.';
alter table inventory.transfer enable row level security;
alter table inventory.transfer force row level security;
create policy tenant_isolation on inventory.transfer
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.transfer_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  transfer_id uuid not null references inventory.transfer(id),
  product_id uuid not null references products.product(id),
  batch_id uuid references inventory.batch(id),
  qty_sent numeric(18,4) not null check (qty_sent > 0),
  qty_received numeric(18,4),
  variance_reason_code_id uuid references kernel.reason_code(id)
);
comment on table inventory.transfer_line is 'Items in a transfer.';
alter table inventory.transfer_line enable row level security;
alter table inventory.transfer_line force row level security;
create policy tenant_isolation on inventory.transfer_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.stock_adjustment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  number text not null,
  location_id uuid not null references inventory.location(id),
  reason_code_id uuid not null references kernel.reason_code(id),
  note text,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'posted', 'rejected')),
  approved_by uuid references kernel.app_user(id),
  posted_at timestamptz,
  unique (company_id, number)
);
comment on table inventory.stock_adjustment is 'A manual change to stock with a reason.';
alter table inventory.stock_adjustment enable row level security;
alter table inventory.stock_adjustment force row level security;
create policy tenant_isolation on inventory.stock_adjustment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.stock_adjustment_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  adjustment_id uuid not null references inventory.stock_adjustment(id),
  product_id uuid not null references products.product(id),
  batch_id uuid references inventory.batch(id),
  qty_change numeric(18,4) not null check (qty_change <> 0)
);
comment on table inventory.stock_adjustment_line is 'Items in an adjustment.';
alter table inventory.stock_adjustment_line enable row level security;
alter table inventory.stock_adjustment_line force row level security;
create policy tenant_isolation on inventory.stock_adjustment_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.stock_count (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  number text not null,
  location_id uuid not null references inventory.location(id),
  status text not null default 'counting' check (status in ('counting', 'review', 'pending_approval', 'posted', 'cancelled')),
  snapshot_at timestamptz not null,
  approved_by uuid references kernel.app_user(id),
  posted_at timestamptz,
  unique (company_id, number)
);
comment on table inventory.stock_count is 'A physical count.';
alter table inventory.stock_count enable row level security;
alter table inventory.stock_count force row level security;
create policy tenant_isolation on inventory.stock_count
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table inventory.stock_count_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  count_id uuid not null references inventory.stock_count(id),
  product_id uuid not null references products.product(id),
  batch_id uuid references inventory.batch(id),
  expected_qty numeric(18,4) not null,
  counted_qty numeric(18,4),
  variance_qty numeric(18,4),
  reason_code_id uuid references kernel.reason_code(id)
);
comment on table inventory.stock_count_line is 'Expected and counted quantities.';
alter table inventory.stock_count_line enable row level security;
alter table inventory.stock_count_line force row level security;
create policy tenant_isolation on inventory.stock_count_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

