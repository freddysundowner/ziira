-- Files and photos attached to any record (docs/files.md). The bytes live in the private file store, never in the
-- database; these rows say what each file is, who made it, which record it belongs to and who may share it.

create table kernel.attachment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  entity_type text not null check (entity_type ~ '^[a-z][a-z0-9_.]{1,59}$'),
  entity_id uuid not null,
  category text not null default 'general' check (category ~ '^[a-z][a-z0-9_]{0,39}$'),
  caption text not null default '' check (length(caption) <= 300),
  visibility text not null default 'staff' check (visibility in ('staff', 'shareable')),
  consent_note text not null default '' check (length(consent_note) <= 300),
  kind text not null check (kind in ('image', 'pdf')),
  content_type text not null check (content_type in ('image/jpeg', 'image/png', 'image/webp', 'application/pdf')),
  original_name text not null default '' check (length(original_name) <= 200),
  size_bytes bigint not null check (size_bytes >= 0),
  checksum text not null check (length(checksum) = 64),
  width integer,
  height integer,
  page_count integer,
  storage_key text not null,
  web_key text,
  thumb_key text,
  web_bytes bigint not null default 0,
  thumb_bytes bigint not null default 0,
  location_stripped boolean not null default false,
  link_epoch integer not null default 0,
  local_id uuid,
  status text not null default 'active' check (status in ('active', 'deleted')),
  deleted_at timestamptz,
  deleted_by uuid references kernel.app_user(id),
  delete_reason text check (length(delete_reason) <= 300),
  blobs_removed boolean not null default false
);
comment on table kernel.attachment is 'A photo or PDF attached to a record (entity_type, entity_id). Bytes are in the private file store under storage_key/web_key/thumb_key. A deleted file keeps its row (who, when, why) and loses its bytes and caption.';
create unique index attachment_local_id_uq on kernel.attachment (tenant_id, local_id) where local_id is not null;
create index attachment_entity_ix on kernel.attachment (tenant_id, entity_type, entity_id) where status = 'active';
create index attachment_company_ix on kernel.attachment (tenant_id, company_id, created_at);
create index attachment_deleted_ix on kernel.attachment (tenant_id, deleted_at) where status = 'deleted' and not blobs_removed;
alter table kernel.attachment enable row level security;
alter table kernel.attachment force row level security;
create policy tenant_isolation on kernel.attachment
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.attachment_access (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  at timestamptz not null default now(),
  file_id uuid not null references kernel.attachment(id),
  company_id uuid references kernel.company(id),
  variant text not null check (variant in ('original', 'web', 'thumb')),
  via text not null check (via in ('staff', 'link', 'api')),
  purpose text not null default '',
  label text not null default '' check (length(label) <= 60),
  user_id uuid references kernel.app_user(id),
  ip text not null default ''
);
comment on table kernel.attachment_access is 'Who opened a file (full size or web copy): a signed-in person, or someone holding a link, with the purpose and label the link was made for.';
create index attachment_access_file_ix on kernel.attachment_access (tenant_id, file_id, at desc);
create index attachment_access_at_ix on kernel.attachment_access (tenant_id, at);
alter table kernel.attachment_access enable row level security;
alter table kernel.attachment_access force row level security;
create policy tenant_isolation on kernel.attachment_access
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
