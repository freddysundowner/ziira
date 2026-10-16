-- Website content: the editable facts and pages behind the marketing site (docs/platform-admin-content.md).
-- Working copies live here and never reach the public; the public endpoint serves only the newest row of
-- site_publish, a frozen snapshot made by an explicit, audited publish.

create table master.site_setting (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by text
);
comment on table master.site_setting is 'Working values of the website settings (company names, contact details, social handles, SEO defaults, banner ...). Typed and validated in code (kernel/site_content.py). Public only through a publish snapshot.';

create table master.site_asset (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  alt text not null default '',
  content_type text not null check (content_type in ('image/png', 'image/jpeg', 'image/webp')),
  width int not null,
  height int not null,
  size_bytes int not null,
  content_hash text not null,
  data bytea not null,
  created_at timestamptz not null default now(),
  created_by text
);
create unique index site_asset_hash_ix on master.site_asset (content_hash);
comment on table master.site_asset is 'Images for the website, re-encoded on upload (metadata removed, pixels limited). Stored here so backups and restores carry them.';

create table master.site_page (
  id uuid primary key default gen_random_uuid(),
  slug text not null check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  locale text not null,
  kind text not null check (kind in ('legal', 'content')),
  title text not null,
  body_md text not null default '',
  seo_title text,
  seo_description text,
  status text not null default 'draft' check (status in ('draft', 'published')),
  version int not null default 1,
  updated_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (slug, locale)
);
comment on table master.site_page is 'Legal and simple content pages (Markdown, sanitised on render). Only status published pages enter a publish snapshot.';

create table master.site_page_version (
  id bigint generated always as identity primary key,
  page_id uuid not null,
  version int not null,
  title text not null,
  body_md text not null,
  seo_title text,
  seo_description text,
  status text not null,
  note text,
  created_at timestamptz not null default now(),
  created_by text,
  unique (page_id, version)
);
comment on table master.site_page_version is 'Every saved state of a page: immutable history; restoring makes a new version.';
create or replace function master.forbid_site_version_change() returns trigger language plpgsql as $$
begin
  raise exception 'Page history cannot be changed' using errcode = '23000';
end $$;
create trigger site_page_version_immutable before update or delete on master.site_page_version
  for each row execute function master.forbid_site_version_change();

create table master.site_publish (
  id bigint generated always as identity primary key,
  published_at timestamptz not null default now(),
  published_by text not null,
  note text,
  version_hash text not null,
  snapshot jsonb not null,
  hook_status text not null default 'skipped' check (hook_status in ('skipped', 'pending', 'ok', 'failed')),
  hook_attempts int not null default 0,
  hook_next_at timestamptz,
  hook_result text
);
comment on table master.site_publish is 'Every publish: who, when, the frozen content that went public (newest row = what the public endpoint serves) and what happened to the site rebuild hook.';
create or replace function master.guard_site_publish() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Publish history cannot be deleted' using errcode = '23000';
  end if;
  if new.snapshot is distinct from old.snapshot or new.version_hash is distinct from old.version_hash
     or new.published_at is distinct from old.published_at or new.published_by is distinct from old.published_by then
    raise exception 'A published snapshot cannot be changed' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger site_publish_guard before update or delete on master.site_publish
  for each row execute function master.guard_site_publish();
