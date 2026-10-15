-- Barcodes: a product may have several (each pack size or supplier label scans to the same product); a code identifies
-- one product within a company.
create table products.product_barcode (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  product_id uuid not null references products.product(id),
  barcode text not null check (barcode = btrim(barcode) and length(barcode) between 1 and 64),
  unique (company_id, barcode)
);
comment on table products.product_barcode is 'Codes a scanner reads for a product; unique per company.';
create index product_barcode_ix1 on products.product_barcode (product_id);
alter table products.product_barcode enable row level security;
alter table products.product_barcode force row level security;
create policy tenant_isolation on products.product_barcode
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index product_barcode_ix2 on products.product_barcode (barcode);
