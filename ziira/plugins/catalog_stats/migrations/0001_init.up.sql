-- Plugin tables live in the plugin's own schema.
create schema if not exists plg_catalog_stats;

create table plg_catalog_stats.company_count (
  tenant_id     uuid not null references kernel.tenant(id),
  company_id    uuid not null references kernel.company(id),
  product_count integer not null default 0,
  updated_at    timestamptz not null default now(),
  primary key (tenant_id, company_id)
);
alter table plg_catalog_stats.company_count enable row level security;
alter table plg_catalog_stats.company_count force row level security;
create policy tenant_isolation on plg_catalog_stats.company_count
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
