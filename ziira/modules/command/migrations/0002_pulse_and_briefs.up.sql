-- Command Center made real: pulse figures (read models the dashboard and briefs read, never raw tables at page
-- load) and the briefs that were composed and sent. WhatsApp is not a channel (SMS, email and in-app are).

update command.brief_schedule set channel = 'in_app' where channel = 'whatsapp';
alter table command.brief_schedule drop constraint if exists brief_schedule_channel_check;
alter table command.brief_schedule add constraint brief_schedule_channel_check check (channel in ('sms', 'email', 'in_app'));
alter table command.brief_schedule alter column channel set default 'in_app';

create table command.pulse_figure (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  day date not null,
  metric text not null,
  label text not null,
  kind text not null check (kind in ('money', 'count', 'percent')),
  value numeric(20,4) not null,
  higher_is_better boolean,
  computed_at timestamptz not null default now()
);
comment on table command.pulse_figure is 'A business figure for a day (company-wide when branch_id is null), supplied by the units.';
create unique index pulse_figure_ux on command.pulse_figure
  (tenant_id, company_id, coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid), day, metric);
create index pulse_figure_ix1 on command.pulse_figure (tenant_id, company_id, day);
alter table command.pulse_figure enable row level security;
alter table command.pulse_figure force row level security;
create policy tenant_isolation on command.pulse_figure
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table command.brief (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  user_id uuid not null references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  kind text not null check (kind in ('daily', 'weekly')),
  brief_date date not null,
  subject text not null,
  body text not null,
  data jsonb not null default '{}',
  delivered_via text not null,
  read_at timestamptz,
  unique (user_id, company_id, kind, brief_date)
);
comment on table command.brief is 'A brief that was composed for a person, as sent, so it can be read again.';
create index brief_ix1 on command.brief (tenant_id, user_id, created_at desc);
alter table command.brief enable row level security;
alter table command.brief force row level security;
create policy tenant_isolation on command.brief
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
