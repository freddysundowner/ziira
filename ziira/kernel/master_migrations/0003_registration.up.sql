-- Self-service registration: a person asks for a business, proves their email, and the platform creates the business.
-- A registration is only a request until the emailed link is used; nothing is provisioned (no database, no login) before.

create table master.registration (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  business_name text not null,
  owner_name text not null,
  password_hash text not null,
  currency char(3) not null,
  phone_country_code text not null default '',
  tax_id text,
  invite_code_hash text,
  token_hash text not null unique,
  ip_address text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  verified_at timestamptz,
  tenant_id uuid references master.tenant(id) on delete set null
);
create index registration_email_ix on master.registration (email, created_at);
create index registration_ip_ix on master.registration (ip_address, created_at);
comment on table master.registration is 'A request to create a business, waiting for its owner to verify their email.';

-- Invitation codes, for platforms that let people register only when invited (registration mode "invite").
create table master.invite_code (
  id uuid primary key default gen_random_uuid(),
  code_hash text not null unique,
  uses_left int not null check (uses_left >= 0),
  expires_at timestamptz,
  note text,
  created_at timestamptz not null default now()
);
