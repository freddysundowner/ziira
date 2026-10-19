-- Custom fields (a business or an industry pack adds its own fields to records: a vehicle plate, a hair type) and the log
-- of what industry packs seeded. Values are never money or stock (the kinds below leave no room for either).

create table kernel.custom_field_def (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid references kernel.company(id),
  entity_type text not null check (entity_type ~ '^[a-z][a-z0-9_.]{1,59}$'),
  key text not null check (key ~ '^[a-z][a-z0-9_]{0,39}$'),
  label text not null check (length(label) between 1 and 80),
  kind text not null check (kind in ('text', 'number', 'date', 'bool', 'choice')),
  choices jsonb not null default '[]'::jsonb,
  required boolean not null default false,
  searchable boolean not null default false,
  sort_order integer not null default 0,
  active boolean not null default true,
  source text not null default 'business' check (source = 'business' or source ~ '^pack:[a-z][a-z0-9_]{1,59}$')
);
comment on table kernel.custom_field_def is 'A field a business (or an industry pack) added to a kind of record. company_id null = the whole business.';
create unique index custom_field_def_uq on kernel.custom_field_def
  (tenant_id, entity_type, key, coalesce(company_id, '00000000-0000-0000-0000-000000000000'::uuid));
create index custom_field_def_ix1 on kernel.custom_field_def (tenant_id, entity_type, sort_order);
alter table kernel.custom_field_def enable row level security;
alter table kernel.custom_field_def force row level security;
create policy tenant_isolation on kernel.custom_field_def
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.custom_field_value (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  updated_by uuid references kernel.app_user(id),
  company_id uuid references kernel.company(id),
  entity_type text not null,
  entity_id uuid not null,
  data jsonb not null default '{}'::jsonb check (jsonb_typeof(data) = 'object' and pg_column_size(data) <= 20000),
  unique (tenant_id, entity_type, entity_id)
);
comment on table kernel.custom_field_value is 'The custom field values of one record, keyed by field key. company_id is the record''s company (for privacy requests).';
alter table kernel.custom_field_value enable row level security;
alter table kernel.custom_field_value force row level security;
create policy tenant_isolation on kernel.custom_field_value
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.pack_seed_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  pack text not null,
  company_id uuid references kernel.company(id),
  seeder text not null,
  item_type text not null,
  item_id uuid not null,
  item_label text not null default '',
  unique (tenant_id, pack, seeder, item_type, item_id)
);
comment on table kernel.pack_seed_log is 'What an industry pack added to a business, so switching the pack off can offer to remove what was never touched.';
alter table kernel.pack_seed_log enable row level security;
alter table kernel.pack_seed_log force row level security;
create policy tenant_isolation on kernel.pack_seed_log
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
