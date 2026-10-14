-- Which businesses a login (an email or a phone number) belongs to, so a person can sign in without saying which business
-- they work for. Only a keyed hash of the login is stored (no raw emails or numbers), and it is only a pointer to the
-- tenants to check: the password is always verified inside the business's own database, so a stale entry is harmless.

create table master.login_directory (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references master.tenant(id) on delete cascade,
  identifier_hash text not null,
  created_at timestamptz not null default now(),
  unique (identifier_hash, tenant_id)
);
create index login_directory_ix1 on master.login_directory (identifier_hash);
comment on table master.login_directory is 'Keyed hash of a login -> the tenants that have a user with it (a pointer, not a source of truth).';
