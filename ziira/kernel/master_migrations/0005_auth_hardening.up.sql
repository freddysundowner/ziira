-- Sign-in protection: counting failed attempts per login and per address so guessing is slowed and then stopped, and
-- password reset links. Keys are keyed hashes (never an email, phone or address in the clear).

create table master.auth_throttle (
  key text primary key,
  failures int not null default 0,
  window_started timestamptz not null default now(),
  locked_until timestamptz,
  updated_at timestamptz not null default now()
);
create index auth_throttle_ix on master.auth_throttle (updated_at);
comment on table master.auth_throttle is 'Failed sign-in style attempts per keyed hash; a lock stops attempts until locked_until.';

create table master.password_reset (
  id uuid primary key default gen_random_uuid(),
  token_hash text not null unique,
  tenant_id uuid not null references master.tenant(id) on delete cascade,
  user_id uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  used_at timestamptz,
  ip_address text
);
create index password_reset_ix on master.password_reset (user_id, created_at);
comment on table master.password_reset is 'A one-use link for choosing a new password; only the hash of the token is kept.';
