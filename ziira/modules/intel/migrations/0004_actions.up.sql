-- Levels 3 and 4 of Intelligence: actions it may propose for a finding (a draft, a price change, a reminder), the rules
-- an owner sets to let routine ones run without a person, and the log of everything done. Nothing here moves money.

alter table intel.finding add column actions_checked_at timestamptz;
comment on column intel.finding.actions_checked_at is 'When the action providers last looked at this finding (null: not yet, or it came back)';

create table intel.action_proposal (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  finding_id uuid not null references intel.finding(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  action_type text not null,
  params jsonb not null,
  params_hash text not null,
  description text not null,
  facts jsonb not null default '{}',
  status text not null default 'proposed'
    check (status in ('proposed', 'approved', 'executed', 'failed', 'rejected', 'expired', 'cancelled')),
  level_at_proposal integer not null check (level_at_proposal between 3 and 4),
  proposed_at timestamptz not null default now(),
  decided_by uuid references kernel.app_user(id),
  decided_at timestamptz,
  decision_note text,
  executed_at timestamptz,
  result jsonb
);
comment on table intel.action_proposal is 'Something Intelligence proposes to do about a finding; a person approves it, or a rule of the owner does';
create unique index action_proposal_ux_live on intel.action_proposal (tenant_id, finding_id, action_type, params_hash)
  where status in ('proposed', 'approved');
create index action_proposal_ix1 on intel.action_proposal (tenant_id, company_id, status, proposed_at);
create index action_proposal_ix2 on intel.action_proposal (tenant_id, finding_id);
alter table intel.action_proposal enable row level security;
alter table intel.action_proposal force row level security;
create policy tenant_isolation on intel.action_proposal
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.auto_rule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  action_type text not null,
  enabled boolean not null default true,
  conditions jsonb not null default '{}',
  daily_cap integer not null check (daily_cap between 1 and 1000),
  paused_at timestamptz,
  note text
);
comment on table intel.auto_rule is 'The owner letting a routine action run by itself, within conditions and a daily limit';
create index auto_rule_ix1 on intel.auto_rule (tenant_id, company_id, action_type);
alter table intel.auto_rule enable row level security;
alter table intel.auto_rule force row level security;
create policy tenant_isolation on intel.auto_rule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.action_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  proposal_id uuid references intel.action_proposal(id),
  finding_id uuid references intel.finding(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  action_type text not null,
  mode text not null check (mode in ('manual', 'automatic')),
  actor_user_id uuid references kernel.app_user(id),
  rule_id uuid references intel.auto_rule(id),
  level integer not null,
  params jsonb not null,
  outcome text not null check (outcome in ('executed', 'failed')),
  message text not null,
  result jsonb
);
comment on table intel.action_log is 'Everything Intelligence did or tried to do, by a person''s approval or by a rule. Never changed.';
create index action_log_ix1 on intel.action_log (tenant_id, company_id, created_at);
create index action_log_ix2 on intel.action_log (tenant_id, rule_id, created_at);
alter table intel.action_log enable row level security;
alter table intel.action_log force row level security;
create policy tenant_isolation on intel.action_log
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger action_log_immutable before update or delete on intel.action_log
  for each row execute function kernel.forbid_change();
