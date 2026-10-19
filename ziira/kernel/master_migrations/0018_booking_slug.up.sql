-- Public booking pages: the address a business shares (/book/<slug>) finds its business here. A slug belongs to exactly
-- one company of one business. Only the slug and the ids live here; no business data.

create table master.booking_slug (
  slug text primary key check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' and length(slug) between 3 and 60),
  tenant_id uuid not null references master.tenant(id),
  company_id uuid not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, company_id)
);
comment on table master.booking_slug is 'Maps the public booking address of a company to its business (tenant) and company.';
