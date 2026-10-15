-- Connect · pictures to read: a scanned statement or a photo is read by the OCR engine in a background job, because it
-- takes a while. The file is kept only until it has been read; the lines read from it wait here until the person has
-- checked and confirmed them (or a day passes), then everything is deleted. A PDF password is never stored.
create table connect.scan (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  filename text not null,
  kind text not null check (kind in ('pdf', 'image')),
  status text not null default 'queued' check (status in ('queued', 'reading', 'ready', 'failed')),
  pages integer not null default 1,
  pages_done integer not null default 0,
  error text,
  data bytea,
  rows jsonb,
  warnings jsonb not null default '[]'
);
comment on table connect.scan is 'A picture waiting to be read, then its lines waiting to be confirmed. Deleted after a day.';
comment on column connect.scan.data is 'The uploaded file; cleared as soon as it has been read.';
create index scan_ix1 on connect.scan (tenant_id, connection_id, created_at desc);
alter table connect.scan enable row level security;
alter table connect.scan force row level security;
create policy tenant_isolation on connect.scan
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
