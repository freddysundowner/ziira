-- Ziira Core 1.0 · schema 'purchasing' (Purchasing and Suppliers) · install migration
-- Requires: kernel, products
-- Suppliers, requests, orders, receipts and bills.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists purchasing;

create table purchasing.supplier (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  kra_pin text,
  phone text,
  email text,
  payment_terms_days integer not null default 0,
  status text not null default 'active' check (status in ('active', 'on_hold', 'inactive')),
  unique (company_id, code)
);
comment on table purchasing.supplier is 'A supplier.';
alter table purchasing.supplier enable row level security;
alter table purchasing.supplier force row level security;
create policy tenant_isolation on purchasing.supplier
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.supplier_bank_account (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  supplier_id uuid not null references purchasing.supplier(id),
  method text not null check (method in ('bank', 'mpesa')),
  bank_name text,
  account_name text,
  account_no_ciphertext bytea,
  account_no_masked text,
  valid_from timestamptz not null,
  valid_to timestamptz,
  approved_by uuid references kernel.app_user(id),
  confirmed_by uuid references kernel.app_user(id),
  confirmation_method text
);
comment on table purchasing.supplier_bank_account is 'Supplier payment details (versioned; changes approved).';
comment on column purchasing.supplier_bank_account.account_no_ciphertext is 'Encrypted';
comment on column purchasing.supplier_bank_account.confirmed_by is 'Person who confirmed directly with the supplier';
alter table purchasing.supplier_bank_account enable row level security;
alter table purchasing.supplier_bank_account force row level security;
create policy tenant_isolation on purchasing.supplier_bank_account
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.purchase_request (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  needed_by date,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'approved', 'rejected', 'ordered')),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number)
);
comment on table purchasing.purchase_request is 'Internal request to buy.';
alter table purchasing.purchase_request enable row level security;
alter table purchasing.purchase_request force row level security;
create policy tenant_isolation on purchasing.purchase_request
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.purchase_request_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  request_id uuid not null references purchasing.purchase_request(id),
  product_id uuid not null references products.product(id),
  quantity numeric(18,4) not null check (quantity > 0),
  note text
);
comment on table purchasing.purchase_request_line is 'Items requested.';
alter table purchasing.purchase_request_line enable row level security;
alter table purchasing.purchase_request_line force row level security;
create policy tenant_isolation on purchasing.purchase_request_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.purchase_order (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  supplier_id uuid not null references purchasing.supplier(id),
  request_id uuid references purchasing.purchase_request(id),
  deliver_to_location_id uuid,
  order_date date not null,
  expected_date date,
  subtotal numeric(18,2) not null default 0,
  tax_total numeric(18,2) not null default 0,
  total numeric(18,2) not null default 0,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'approved', 'sent', 'part_received', 'received', 'closed', 'cancelled')),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number)
);
comment on table purchasing.purchase_order is 'Order to a supplier.';
comment on column purchasing.purchase_order.deliver_to_location_id is 'Soft reference to inventory.location';
create index purchase_order_ix1 on purchasing.purchase_order (supplier_id, status);
alter table purchasing.purchase_order enable row level security;
alter table purchasing.purchase_order force row level security;
create policy tenant_isolation on purchasing.purchase_order
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.purchase_order_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  order_id uuid not null references purchasing.purchase_order(id),
  product_id uuid not null references products.product(id),
  uom_id uuid not null references products.uom(id),
  quantity numeric(18,4) not null check (quantity > 0),
  unit_cost numeric(18,6) not null,
  tax_code_id uuid not null references products.tax_code(id),
  qty_received numeric(18,4) not null default 0,
  qty_billed numeric(18,4) not null default 0
);
comment on table purchasing.purchase_order_line is 'Items ordered.';
alter table purchasing.purchase_order_line enable row level security;
alter table purchasing.purchase_order_line force row level security;
create policy tenant_isolation on purchasing.purchase_order_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.goods_receipt (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  order_id uuid references purchasing.purchase_order(id),
  supplier_id uuid not null references purchasing.supplier(id),
  location_id uuid,
  received_at timestamptz not null,
  delivery_note_no text,
  status text not null default 'draft' check (status in ('draft', 'posted', 'reversed')),
  unique (company_id, number)
);
comment on table purchasing.goods_receipt is 'Goods received against an order.';
comment on column purchasing.goods_receipt.location_id is 'Soft reference to inventory.location';
alter table purchasing.goods_receipt enable row level security;
alter table purchasing.goods_receipt force row level security;
create policy tenant_isolation on purchasing.goods_receipt
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.goods_receipt_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  receipt_id uuid not null references purchasing.goods_receipt(id),
  order_line_id uuid references purchasing.purchase_order_line(id),
  product_id uuid not null references products.product(id),
  batch_no text,
  expiry_date date,
  quantity numeric(18,4) not null check (quantity > 0),
  unit_cost numeric(18,6) not null,
  landed_cost numeric(18,2) not null default 0
);
comment on table purchasing.goods_receipt_line is 'Items received.';
alter table purchasing.goods_receipt_line enable row level security;
alter table purchasing.goods_receipt_line force row level security;
create policy tenant_isolation on purchasing.goods_receipt_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.supplier_bill (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  supplier_id uuid not null references purchasing.supplier(id),
  supplier_invoice_no text not null,
  bill_date date not null,
  due_date date not null,
  subtotal numeric(18,2) not null,
  tax_total numeric(18,2) not null,
  total numeric(18,2) not null,
  amount_paid numeric(18,2) not null default 0,
  match_status text not null default 'pending' check (match_status in ('pending', 'matched', 'exception', 'not_required')),
  etims_ref text,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'posted', 'part_paid', 'paid', 'cancelled')),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number),
  unique (supplier_id, supplier_invoice_no)
);
comment on table purchasing.supplier_bill is 'Supplier invoice.';
create index supplier_bill_ix1 on purchasing.supplier_bill (tenant_id, due_date);
alter table purchasing.supplier_bill enable row level security;
alter table purchasing.supplier_bill force row level security;
create policy tenant_isolation on purchasing.supplier_bill
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.supplier_bill_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  bill_id uuid not null references purchasing.supplier_bill(id),
  order_line_id uuid references purchasing.purchase_order_line(id),
  receipt_line_id uuid references purchasing.goods_receipt_line(id),
  product_id uuid references products.product(id),
  expense_account_id uuid,
  description text,
  quantity numeric(18,4) not null,
  unit_cost numeric(18,6) not null,
  tax_code_id uuid references products.tax_code(id),
  tax_amount numeric(18,2) not null default 0,
  line_total numeric(18,2) not null
);
comment on table purchasing.supplier_bill_line is 'Lines of a supplier bill.';
comment on column purchasing.supplier_bill_line.expense_account_id is 'Soft reference to finance.account, for non-stock lines';
alter table purchasing.supplier_bill_line enable row level security;
alter table purchasing.supplier_bill_line force row level security;
create policy tenant_isolation on purchasing.supplier_bill_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.supplier_price (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  supplier_id uuid not null references purchasing.supplier(id),
  product_id uuid not null references products.product(id),
  unit_cost numeric(18,6) not null,
  effective_date date not null,
  source_type text not null,
  source_id uuid not null
);
comment on table purchasing.supplier_price is 'Cost history per supplier and product.';
create index supplier_price_ix1 on purchasing.supplier_price (product_id, effective_date);
alter table purchasing.supplier_price enable row level security;
alter table purchasing.supplier_price force row level security;
create policy tenant_isolation on purchasing.supplier_price
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

