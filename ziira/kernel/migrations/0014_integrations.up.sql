-- Public API and outgoing webhooks: API key scopes (read-only, company/branch), limits and usage; webhook endpoints,
-- their deliveries and every attempt.

alter table kernel.api_key add column read_only boolean not null default false;
alter table kernel.api_key add column company_id uuid references kernel.company(id);
alter table kernel.api_key add column branch_id uuid references kernel.branch(id);
alter table kernel.api_key add column rate_limit_per_minute integer
  check (rate_limit_per_minute is null or rate_limit_per_minute between 1 and 100000);
alter table kernel.api_key add column last_used_at timestamptz;
alter table kernel.api_key add column last_ip text;
alter table kernel.api_key add column use_count bigint not null default 0;
alter table kernel.api_key add column window_started timestamptz;
alter table kernel.api_key add column window_count integer not null default 0;
alter table kernel.api_key add column rotated_from uuid references kernel.api_key(id);
comment on column kernel.api_key.read_only is 'A read-only key can make GET requests only.';
comment on column kernel.api_key.company_id is 'Limits the key to one company (null: all); branch_id limits it to one branch.';
comment on column kernel.api_key.window_count is 'Requests in the current one-minute window (the per-key rate limit).';

create table kernel.webhook_endpoint (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  name text not null,
  url text not null,
  event_types text[] not null,
  secret_ciphertext bytea not null,
  secret_hint text not null,
  status text not null default 'active' check (status in ('active', 'paused', 'disabled')),
  disabled_reason text,
  consecutive_failures integer not null default 0,
  last_success_at timestamptz,
  last_failure_at timestamptz
);
comment on table kernel.webhook_endpoint is 'A web address of the business that is told when chosen events happen. The signing secret is encrypted and shown once.';
alter table kernel.webhook_endpoint enable row level security;
alter table kernel.webhook_endpoint force row level security;
create policy tenant_isolation on kernel.webhook_endpoint
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.webhook_delivery (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  endpoint_id uuid not null references kernel.webhook_endpoint(id) on delete cascade,
  event_id uuid not null default gen_random_uuid(),
  event_type text not null,
  aggregate_type text,
  aggregate_id uuid,
  body text,
  body_sha256 text not null,
  body_preview text not null,
  body_bytes integer not null,
  status text not null default 'pending' check (status in ('pending', 'delivered', 'failed', 'cancelled')),
  attempts integer not null default 0,
  max_attempts integer not null,
  expires_at timestamptz not null,
  last_attempt_at timestamptz,
  next_attempt_at timestamptz,
  delivered_at timestamptz,
  last_status_code integer,
  last_duration_ms integer,
  last_error text,
  is_test boolean not null default false
);
comment on table kernel.webhook_delivery is 'One event for one endpoint. The body is kept for a few days (to retry and redeliver), then only its hash and first bytes.';
create index webhook_delivery_ix1 on kernel.webhook_delivery (endpoint_id, created_at desc);
create index webhook_delivery_ix2 on kernel.webhook_delivery (created_at);
alter table kernel.webhook_delivery enable row level security;
alter table kernel.webhook_delivery force row level security;
create policy tenant_isolation on kernel.webhook_delivery
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.webhook_attempt (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  delivery_id uuid not null references kernel.webhook_delivery(id) on delete cascade,
  attempted_at timestamptz not null default now(),
  ok boolean not null,
  status_code integer,
  duration_ms integer,
  error text
);
create index webhook_attempt_ix1 on kernel.webhook_attempt (delivery_id, attempted_at);
alter table kernel.webhook_attempt enable row level security;
alter table kernel.webhook_attempt force row level security;
create policy tenant_isolation on kernel.webhook_attempt
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
