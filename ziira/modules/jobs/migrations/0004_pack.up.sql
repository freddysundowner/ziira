-- Ziira Core · schema 'jobs' · 0004 · what an industry pack leaves behind: its first-run steps and its sample week
alter table jobs.setting add column pack_name text;
comment on column jobs.setting.pack_name is 'The industry pack whose suggestions were applied to these settings (applied once).';

create table jobs.pack_step (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  pack text not null,
  step_id text not null,
  title text not null,
  hint text,
  to_path text,
  check_key text,
  sort_order integer not null default 0,
  done_at timestamptz,
  hidden boolean not null default false,
  unique (company_id, pack, step_id)
);
comment on table jobs.pack_step is 'The first-run checklist of an industry pack: a few plain steps that tick themselves.';

create table jobs.sample_recipe (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  pack text not null,
  recipe jsonb not null default '{}',
  unique (company_id, pack)
);
comment on table jobs.sample_recipe is 'The sample week an industry pack ships, kept until it is loaded.';

create table jobs.sample_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  pack text not null,
  item_type text not null,
  item_id uuid not null,
  label text,
  unique (item_type, item_id)
);
comment on table jobs.sample_item is 'Every row the sample week made, so that removing it takes away exactly that.';

do $$
declare t text;
begin
  foreach t in array array['pack_step', 'sample_recipe', 'sample_item']
  loop
    execute format('alter table jobs.%I enable row level security', t);
    execute format('alter table jobs.%I force row level security', t);
    execute format('create policy tenant_isolation on jobs.%I using (tenant_id = kernel.current_tenant()) '
                   'with check (tenant_id = kernel.current_tenant())', t);
  end loop;
end $$;
