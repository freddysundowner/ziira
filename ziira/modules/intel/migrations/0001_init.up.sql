-- Ziira Core 1.0 · schema 'intel' (Ziira Intelligence store) · install migration
-- Requires: kernel
-- Owned by the Ziira Intelligence service; shown here because Core reads findings from it.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists intel;

create table intel.check_definition (
  code text not null,
  version integer not null,
  title text not null,
  severity_default text not null check (severity_default in ('info', 'low', 'medium', 'high', 'critical')),
  definition jsonb not null,
  is_active boolean not null default true,
  id uuid primary key default gen_random_uuid(),
  unique (code, version)
);
comment on table intel.check_definition is 'Versioned checks (platform level).';

create table intel.finding (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  check_id uuid not null references intel.check_definition(id),
  company_id uuid references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  entity_type text,
  entity_id uuid,
  period_start date,
  period_end date,
  value numeric(20,4),
  expected_value numeric(20,4),
  severity text not null check (severity in ('info', 'low', 'medium', 'high', 'critical')),
  evidence jsonb not null,
  explanation text,
  status text not null default 'new' check (status in ('new', 'sent', 'acknowledged', 'explained', 'resolved', 'dismissed')),
  owner_user_id uuid references kernel.app_user(id),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  resolved_at timestamptz
);
comment on table intel.finding is 'A result of a check needing attention.';
comment on column intel.finding.evidence is 'Record IDs behind the finding';
comment on column intel.finding.explanation is 'Plain-language text from the AI layer';
create index finding_ix1 on intel.finding (tenant_id, status, severity);
create index finding_ix2 on intel.finding (branch_id, period_start);
alter table intel.finding enable row level security;
alter table intel.finding force row level security;
create policy tenant_isolation on intel.finding
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.finding_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  finding_id uuid not null references intel.finding(id),
  event text not null,
  user_id uuid references kernel.app_user(id),
  channel text,
  note text
);
comment on table intel.finding_event is 'History of a finding: sent, explained, resolved.';
alter table intel.finding_event enable row level security;
alter table intel.finding_event force row level security;
create policy tenant_isolation on intel.finding_event
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.baseline (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  metric text not null,
  dimension jsonb not null,
  mean numeric(20,6),
  stddev numeric(20,6),
  p95 numeric(20,6),
  sample_size integer not null,
  computed_at timestamptz not null
);
comment on table intel.baseline is 'Normal ranges per tenant, used to detect unusual values.';
comment on column intel.baseline.metric is 'e.g. void_rate';
comment on column intel.baseline.dimension is 'e.g. branch, cashier, weekday';
create index baseline_ix1 on intel.baseline (tenant_id, metric);
alter table intel.baseline enable row level security;
alter table intel.baseline force row level security;
create policy tenant_isolation on intel.baseline
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

