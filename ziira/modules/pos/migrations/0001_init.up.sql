-- Ziira Core 1.0 · schema 'pos' (Point of Sale and Sales) · install migration
-- Requires: kernel, products, inventory, payments
-- POS devices, till sessions, sales, quotations, orders, invoices and returns.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists pos;

create table pos.pos_device (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  branch_id uuid not null references kernel.branch(id),
  name text not null,
  device_key_hash text not null unique,
  status text not null default 'active' check (status in ('active', 'blocked')),
  last_sync_at timestamptz
);
comment on table pos.pos_device is 'A registered POS device.';
alter table pos.pos_device enable row level security;
alter table pos.pos_device force row level security;
create policy tenant_isolation on pos.pos_device
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.till_session (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  branch_id uuid not null references kernel.branch(id),
  device_id uuid not null references pos.pos_device(id),
  cash_account_id uuid not null references payments.payment_account(id),
  cashier_id uuid not null references kernel.app_user(id),
  business_date date not null,
  opened_at timestamptz not null,
  opening_float numeric(18,2) not null default 0,
  closed_at timestamptz,
  expected_cash numeric(18,2),
  counted_cash numeric(18,2),
  variance numeric(18,2),
  variance_reason_code_id uuid references kernel.reason_code(id),
  status text not null default 'open' check (status in ('open', 'closed'))
);
comment on table pos.till_session is 'A cashier''s session with a cash float.';
create index till_session_ix1 on pos.till_session (branch_id, business_date);
alter table pos.till_session enable row level security;
alter table pos.till_session force row level security;
create policy tenant_isolation on pos.till_session
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sale (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  device_id uuid references pos.pos_device(id),
  local_id uuid not null,
  till_session_id uuid references pos.till_session(id),
  customer_id uuid,
  cashier_id uuid not null references kernel.app_user(id),
  business_date date not null,
  sold_at timestamptz not null,
  subtotal numeric(18,2) not null,
  discount_total numeric(18,2) not null default 0,
  tax_total numeric(18,2) not null,
  total numeric(18,2) not null,
  paid_total numeric(18,2) not null default 0,
  status text not null default 'posted' check (status in ('posted', 'voided')),
  voided_by uuid references kernel.app_user(id),
  voided_at timestamptz,
  void_reason_code_id uuid references kernel.reason_code(id),
  synced_offline boolean not null default false,
  unique (company_id, number),
  unique (tenant_id, local_id),
  check (status <> 'voided' or void_reason_code_id is not null)
);
comment on table pos.sale is 'A POS or counter sale.';
comment on column pos.sale.number is 'Per-device series';
comment on column pos.sale.local_id is 'Device-generated ID for offline sync';
comment on column pos.sale.customer_id is 'Soft reference to crm.customer';
create index sale_ix1 on pos.sale (branch_id, business_date);
create index sale_ix2 on pos.sale (cashier_id, business_date);
alter table pos.sale enable row level security;
alter table pos.sale force row level security;
create policy tenant_isolation on pos.sale
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sale_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  sale_id uuid not null references pos.sale(id),
  line_no smallint not null,
  product_id uuid not null references products.product(id),
  uom_id uuid not null references products.uom(id),
  batch_id uuid references inventory.batch(id),
  quantity numeric(18,4) not null check (quantity > 0),
  list_price numeric(18,2) not null,
  unit_price numeric(18,2) not null,
  discount_amount numeric(18,2) not null default 0,
  price_reason_code_id uuid references kernel.reason_code(id),
  tax_code_id uuid not null references products.tax_code(id),
  tax_amount numeric(18,2) not null,
  line_total numeric(18,2) not null,
  cost_amount numeric(18,2),
  unique (sale_id, line_no)
);
comment on table pos.sale_line is 'Items in a sale.';
comment on column pos.sale_line.price_reason_code_id is 'Required when price or discount exceeds policy';
comment on column pos.sale_line.cost_amount is 'Set at posting from average cost';
alter table pos.sale_line enable row level security;
alter table pos.sale_line force row level security;
create policy tenant_isolation on pos.sale_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sale_payment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  sale_id uuid not null references pos.sale(id),
  method text not null check (method in ('cash', 'mpesa', 'card', 'credit', 'other')),
  payment_account_id uuid references payments.payment_account(id),
  amount numeric(18,2) not null,
  external_ref text,
  payment_id uuid references payments.payment(id)
);
comment on table pos.sale_payment is 'How a sale was paid.';
comment on column pos.sale_payment.external_ref is 'M-Pesa receipt code if known';
alter table pos.sale_payment enable row level security;
alter table pos.sale_payment force row level security;
create policy tenant_isolation on pos.sale_payment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sales_document (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  doc_kind text not null check (doc_kind in ('quotation', 'order')),
  number text not null,
  customer_id uuid,
  doc_date date not null,
  valid_until date,
  source_quotation_id uuid references pos.sales_document(id),
  total numeric(18,2) not null default 0,
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'sent', 'confirmed', 'fulfilled', 'cancelled', 'expired')),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number)
);
comment on table pos.sales_document is 'Quotation or sales order.';
comment on column pos.sales_document.customer_id is 'Soft reference to crm.customer';
alter table pos.sales_document enable row level security;
alter table pos.sales_document force row level security;
create policy tenant_isolation on pos.sales_document
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sales_document_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  document_id uuid not null references pos.sales_document(id),
  product_id uuid not null references products.product(id),
  uom_id uuid not null references products.uom(id),
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,2) not null,
  discount_amount numeric(18,2) not null default 0,
  tax_code_id uuid not null references products.tax_code(id),
  line_total numeric(18,2) not null,
  qty_delivered numeric(18,4) not null default 0
);
comment on table pos.sales_document_line is 'Lines of a quotation or order.';
alter table pos.sales_document_line enable row level security;
alter table pos.sales_document_line force row level security;
create policy tenant_isolation on pos.sales_document_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sales_invoice (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  customer_id uuid not null,
  sale_id uuid references pos.sale(id),
  sales_order_id uuid references pos.sales_document(id),
  issue_date date not null,
  due_date date not null,
  subtotal numeric(18,2) not null,
  tax_total numeric(18,2) not null,
  total numeric(18,2) not null,
  amount_paid numeric(18,2) not null default 0,
  status text not null default 'issued' check (status in ('draft', 'issued', 'part_paid', 'paid', 'cancelled')),
  unique (company_id, number)
);
comment on table pos.sales_invoice is 'A tax invoice to a customer (credit or B2B).';
comment on column pos.sales_invoice.customer_id is 'Soft reference to crm.customer';
create index sales_invoice_ix1 on pos.sales_invoice (customer_id, status);
create index sales_invoice_ix2 on pos.sales_invoice (tenant_id, due_date);
alter table pos.sales_invoice enable row level security;
alter table pos.sales_invoice force row level security;
create policy tenant_isolation on pos.sales_invoice
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sales_invoice_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  invoice_id uuid not null references pos.sales_invoice(id),
  product_id uuid not null references products.product(id),
  uom_id uuid not null references products.uom(id),
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,2) not null,
  discount_amount numeric(18,2) not null default 0,
  tax_code_id uuid not null references products.tax_code(id),
  tax_amount numeric(18,2) not null,
  line_total numeric(18,2) not null
);
comment on table pos.sales_invoice_line is 'Lines of an invoice.';
alter table pos.sales_invoice_line enable row level security;
alter table pos.sales_invoice_line force row level security;
create policy tenant_isolation on pos.sales_invoice_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sales_return (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  original_sale_id uuid references pos.sale(id),
  original_invoice_id uuid references pos.sales_invoice(id),
  reason_code_id uuid not null references kernel.reason_code(id),
  refund_method text not null check (refund_method in ('cash', 'mpesa', 'credit_note', 'exchange')),
  total numeric(18,2) not null,
  restock_location_id uuid references inventory.location(id),
  status text not null default 'draft' check (status in ('draft', 'pending_approval', 'posted', 'rejected')),
  approved_by uuid references kernel.app_user(id),
  unique (company_id, number),
  check (original_sale_id is not null or original_invoice_id is not null)
);
comment on table pos.sales_return is 'Return of goods; produces a credit note.';
alter table pos.sales_return enable row level security;
alter table pos.sales_return force row level security;
create policy tenant_isolation on pos.sales_return
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.sales_return_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  return_id uuid not null references pos.sales_return(id),
  product_id uuid not null references products.product(id),
  batch_id uuid references inventory.batch(id),
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,2) not null,
  tax_amount numeric(18,2) not null,
  line_total numeric(18,2) not null
);
comment on table pos.sales_return_line is 'Items returned.';
alter table pos.sales_return_line enable row level security;
alter table pos.sales_return_line force row level security;
create policy tenant_isolation on pos.sales_return_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

