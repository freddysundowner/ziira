-- Less noise: a person can put a finding aside for a few days (it comes back when the time is up, or sooner if it gets
-- worse), and can say "this is normal" for a branch, a person or everywhere, which stops that kind of thing being raised.
-- Stored findings are never rewritten by either: the screens simply leave snoozed ones out for now.

alter table intel.finding add column snoozed_until timestamptz;
comment on column intel.finding.snoozed_until is 'Put aside until this moment; it is shown again after it, or earlier if the finding gets worse';
create index finding_ix_snoozed on intel.finding (tenant_id, snoozed_until) where snoozed_until is not null;

create table intel.suppression_rule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  check_code text not null,
  branch_id uuid references kernel.branch(id),
  entity_type text,
  entity_id uuid,
  scope_label text not null default '',
  until_date date,
  reason text,
  removed_at timestamptz,
  removed_by uuid references kernel.app_user(id),
  check ((entity_type is null) = (entity_id is null))
);
comment on table intel.suppression_rule is 'A business saying a kind of finding is normal for a branch or a person (for a while, or always), so it is not raised';
comment on column intel.suppression_rule.until_date is 'Last day the rule applies (null: always)';
create index suppression_rule_ix1 on intel.suppression_rule (tenant_id, company_id, check_code) where removed_at is null;
alter table intel.suppression_rule enable row level security;
alter table intel.suppression_rule force row level security;
create policy tenant_isolation on intel.suppression_rule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
