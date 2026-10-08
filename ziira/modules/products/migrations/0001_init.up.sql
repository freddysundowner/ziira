-- Ziira Core 1.0 · schema 'products' (Products and Pricing) · install migration
-- Requires: kernel
-- One catalogue used by sales, purchasing and inventory.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists products;

create table products.category (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  parent_id uuid references products.category(id),
  name text not null
);
comment on table products.category is 'Product category tree.';
alter table products.category enable row level security;
alter table products.category force row level security;
create policy tenant_isolation on products.category
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.uom (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  code text not null,
  name text not null,
  unique (tenant_id, code)
);
comment on table products.uom is 'Units of measure.';
comment on column products.uom.code is 'e.g. PCS, CTN, KG';
alter table products.uom enable row level security;
alter table products.uom force row level security;
create policy tenant_isolation on products.uom
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.tax_code (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  code text not null,
  name text not null,
  vat_rate numeric(5,2) not null,
  etims_tax_type text not null,
  is_active boolean not null default true,
  unique (tenant_id, code)
);
comment on table products.tax_code is 'VAT class and eTIMS tax type.';
comment on column products.tax_code.vat_rate is 'Percent';
alter table products.tax_code enable row level security;
alter table products.tax_code force row level security;
create policy tenant_isolation on products.tax_code
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.product (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  sku text not null,
  name text not null,
  category_id uuid references products.category(id),
  product_type text not null default 'stock' check (product_type in ('stock', 'non_stock', 'service')),
  base_uom_id uuid not null references products.uom(id),
  tax_code_id uuid not null references products.tax_code(id),
  etims_item_class text,
  is_batch_tracked boolean not null default false,
  reorder_level numeric(18,4),
  is_active boolean not null default true,
  unique (company_id, sku)
);
comment on table products.product is 'A product or service.';
comment on column products.product.etims_item_class is 'KRA item classification code';
create index product_ix1 on products.product (tenant_id, name);
alter table products.product enable row level security;
alter table products.product force row level security;
create policy tenant_isolation on products.product
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.product_uom (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  product_id uuid not null references products.product(id),
  uom_id uuid not null references products.uom(id),
  factor_to_base numeric(18,6) not null check (factor_to_base > 0),
  unique (product_id, uom_id)
);
comment on table products.product_uom is 'Other units a product is sold or bought in.';
comment on column products.product_uom.factor_to_base is 'e.g. 1 carton = 24 pieces';
alter table products.product_uom enable row level security;
alter table products.product_uom force row level security;
create policy tenant_isolation on products.product_uom
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.barcode (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  product_id uuid not null references products.product(id),
  uom_id uuid references products.uom(id),
  code text not null,
  unique (tenant_id, code)
);
comment on table products.barcode is 'Barcodes per product and unit.';
alter table products.barcode enable row level security;
alter table products.barcode force row level security;
create policy tenant_isolation on products.barcode
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.price_list (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  branch_id uuid references kernel.branch(id),
  customer_group text,
  currency char(3) not null default 'KES',
  is_default boolean not null default false
);
comment on table products.price_list is 'A set of prices, optionally for a branch or customer group.';
comment on column products.price_list.branch_id is 'Null = all branches';
alter table products.price_list enable row level security;
alter table products.price_list force row level security;
create policy tenant_isolation on products.price_list
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table products.price_list_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  price_list_id uuid not null references products.price_list(id),
  product_id uuid not null references products.product(id),
  uom_id uuid not null references products.uom(id),
  price numeric(18,2) not null check (price >= 0),
  valid_from date not null,
  valid_to date,
  approved_by uuid references kernel.app_user(id)
);
comment on table products.price_list_item is 'Dated price for a product (versioned).';
comment on column products.price_list_item.price is 'Tax-inclusive selling price';
create index price_list_item_ix1 on products.price_list_item (price_list_id, product_id, valid_from);
alter table products.price_list_item enable row level security;
alter table products.price_list_item force row level security;
create policy tenant_isolation on products.price_list_item
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

