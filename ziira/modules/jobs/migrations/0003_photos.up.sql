-- Ziira Core · schema 'jobs' · 0003 · photo kinds and the photos a kind of job must have
-- The photos themselves are kept by the kernel files service (attached to jobs.job); this only names the kinds of
-- photo a workshop takes and the rule "this kind of job needs these photos before it reaches this stage".

create table jobs.photo_category (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  position integer not null default 0,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table jobs.photo_category is 'A kind of photo the workshop takes (intake, damage, odometer, fuel gauge, progress, old part ...).';
alter table jobs.photo_category enable row level security;
alter table jobs.photo_category force row level security;
create policy tenant_isolation on jobs.photo_category
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

alter table jobs.job_type
  add column required_photos jsonb not null default '[]';
comment on column jobs.job_type.required_photos is 'A list of {"category": code, "min": n, "before": stage role}: photos needed before a job of this type reaches that stage.';

alter table jobs.setting
  add column required_photos text not null default 'warn' check (required_photos in ('off', 'warn', 'block'));
comment on column jobs.setting.required_photos is 'What happens when a job moves on without the photos its job type asks for: off, warn or block.';
