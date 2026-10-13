-- The exceptions inbox (things people must look at: negative stock, offline sales that conflicted, till shortages,
-- unmatched payments) and the job queue (work to do later or again: STK status checks, retries).

create table kernel.exception_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  unit_name text not null,
  kind text not null,
  severity text not null default 'medium' check (severity in ('info', 'low', 'medium', 'high', 'critical')),
  company_id uuid references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  ref_type text,
  ref_id uuid,
  amount numeric(18,2),
  message text not null,
  dedupe_key text,
  status text not null default 'open' check (status in ('open', 'explained', 'resolved', 'dismissed')),
  assigned_to uuid references kernel.app_user(id),
  resolution_note text,
  resolved_by uuid references kernel.app_user(id),
  resolved_at timestamptz,
  unique (tenant_id, dedupe_key)
);
comment on table kernel.exception_item is 'Something a person must review; raised by units, worked in the exceptions inbox.';
create index exception_item_ix1 on kernel.exception_item (tenant_id, status, created_at);
alter table kernel.exception_item enable row level security;
alter table kernel.exception_item force row level security;
create policy tenant_isolation on kernel.exception_item
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.job (
  id bigint generated always as identity primary key,
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  job_type text not null,
  payload jsonb not null default '{}',
  run_at timestamptz not null default now(),
  attempts integer not null default 0,
  max_attempts integer not null default 8,
  status text not null default 'queued' check (status in ('queued', 'done', 'failed')),
  last_error text,
  finished_at timestamptz,
  dedupe_key text,
  unique (tenant_id, dedupe_key)
);
comment on table kernel.job is 'Work to do later (or again after a failure). Run by `ziira worker`.';
create index job_ix1 on kernel.job (status, run_at);
alter table kernel.job enable row level security;
alter table kernel.job force row level security;
create policy tenant_isolation on kernel.job
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
