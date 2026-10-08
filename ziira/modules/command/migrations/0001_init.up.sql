-- Ziira Core 1.0 · schema 'command' (Command Center) · install migration
-- Requires: kernel
-- User preferences for dashboards and briefs. Findings live in Ziira Intelligence.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists command;

create table command.brief_schedule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  user_id uuid not null references kernel.app_user(id),
  kind text not null check (kind in ('daily', 'weekly')),
  channel text not null default 'whatsapp' check (channel in ('whatsapp', 'email', 'in_app')),
  send_time time not null,
  weekday smallint check (weekday between 1 and 7),
  is_active boolean not null default true,
  unique (user_id, kind)
);
comment on table command.brief_schedule is 'When and how each user receives briefs.';
alter table command.brief_schedule enable row level security;
alter table command.brief_schedule force row level security;
create policy tenant_isolation on command.brief_schedule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table command.dashboard_widget (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  user_id uuid not null references kernel.app_user(id),
  widget_code text not null,
  position smallint not null,
  settings jsonb not null default '{}'
);
comment on table command.dashboard_widget is 'Widgets on a user''s Command Center.';
alter table command.dashboard_widget enable row level security;
alter table command.dashboard_widget force row level security;
create policy tenant_isolation on command.dashboard_widget
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

