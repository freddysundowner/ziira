-- Findings made usable: each check has a stable code, a finding has a fingerprint (so a problem seen again is the same
-- finding, not a new one), a plain-language summary, a recommended action and the money at stake. A business can switch
-- a check off or change its limits. Baselines belong to a company.

alter table intel.check_definition add column if not exists area text not null default 'general';
alter table intel.check_definition add column if not exists description text not null default '';

alter table intel.finding add column check_code text;
alter table intel.finding add column fingerprint text;
alter table intel.finding add column summary text;
alter table intel.finding add column recommended_action text;
alter table intel.finding add column amount numeric(20,2);
alter table intel.finding add column alerted_at timestamptz;
alter table intel.finding add column area text;
alter table intel.finding alter column check_id drop not null;
create unique index finding_ux_fingerprint on intel.finding (tenant_id, check_code, fingerprint);
create index finding_ix3 on intel.finding (tenant_id, company_id, status, severity);
comment on column intel.finding.fingerprint is 'Identifies the problem (which record, which period): seen again, it is the same finding';
comment on column intel.finding.amount is 'Money at stake in the company currency, used to rank findings';

create index finding_event_ix1 on intel.finding_event (tenant_id, finding_id, created_at);

alter table intel.baseline add column company_id uuid references kernel.company(id);
create index baseline_ix2 on intel.baseline (tenant_id, company_id, metric);

create table intel.check_setting (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  check_code text not null,
  enabled boolean not null default true,
  params jsonb not null default '{}',
  unique (tenant_id, check_code)
);
comment on table intel.check_setting is 'A business switching a check off, or changing its limits.';
alter table intel.check_setting enable row level security;
alter table intel.check_setting force row level security;
create policy tenant_isolation on intel.check_setting
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
