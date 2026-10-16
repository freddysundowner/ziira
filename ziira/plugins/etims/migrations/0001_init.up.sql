-- The status of each document the plugin sends to the tax authority. The plugin owns this, so sales and invoices carry
-- no tax-authority columns (design: docs/parked/etims.md). Nothing writes to it yet: the skeleton has no behaviour.
create schema if not exists plg_etims;

create table plg_etims.submission (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  company_id uuid not null references kernel.company(id),
  doc_type text not null,            -- sale | credit_note | purchase (soft reference to the document's unit)
  doc_id uuid not null,
  status text not null default 'pending' check (status in ('pending', 'submitted', 'failed')),
  authority_ref text,                -- the invoice number the authority issued
  signature text,
  qr_data text,
  attempts integer not null default 0,
  last_error text,
  unique (tenant_id, doc_type, doc_id)
);
alter table plg_etims.submission enable row level security;
alter table plg_etims.submission force row level security;
create policy tenant_isolation on plg_etims.submission
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
