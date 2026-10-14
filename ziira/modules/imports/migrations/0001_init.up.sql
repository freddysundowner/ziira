-- Ziira Core 1.0 · schema 'imports' (Data Import) · install migration
-- Requires: kernel
-- Staging area for files being imported: a batch per uploaded file, a row per line of the file.
-- Business records are never written here; rows are imported through the owning units' services.

create schema if not exists imports;

create table imports.batch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  company_id uuid not null references kernel.company(id),
  kind text not null,
  filename text not null,
  status text not null default 'uploaded' check (status in ('uploaded', 'validated', 'committing', 'done')),
  delimiter text not null,
  headers jsonb not null,
  mapping jsonb not null default '{}',
  options jsonb not null default '{}',
  warnings jsonb not null default '[]',
  committed_by uuid references kernel.app_user(id),
  committed_at timestamptz,
  finished_at timestamptz
);
comment on table imports.batch is 'One uploaded file being imported.';
create index batch_ix1 on imports.batch (tenant_id, created_at desc);
alter table imports.batch enable row level security;
alter table imports.batch force row level security;
create policy tenant_isolation on imports.batch
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table imports.batch_row (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  batch_id uuid not null references imports.batch(id) on delete cascade,
  row_no integer not null,
  raw jsonb not null,
  parsed jsonb not null default '{}',
  status text not null default 'pending'
    check (status in ('pending', 'valid', 'invalid', 'imported', 'skipped', 'failed')),
  errors jsonb not null default '[]',
  record_id uuid,
  updated_at timestamptz,
  unique (batch_id, row_no)
);
comment on table imports.batch_row is 'A line of the file: raw cells, the mapped values, and what became of it.';
comment on column imports.batch_row.record_id is 'The record created in the owning unit (a soft reference).';
create index batch_row_ix1 on imports.batch_row (batch_id, status, row_no);
alter table imports.batch_row enable row level security;
alter table imports.batch_row force row level security;
create policy tenant_isolation on imports.batch_row
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
