-- What a company's accountant calls each account in their own software (used by the journal export).

create table finance.account_mapping (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  account_id uuid not null references finance.account(id),
  external_code text,
  external_name text,
  check (external_code is not null or external_name is not null),
  unique (company_id, account_id)
);
comment on table finance.account_mapping is 'An account''s code and name in the accountant''s own software, for exports.';
alter table finance.account_mapping enable row level security;
alter table finance.account_mapping force row level security;
create policy tenant_isolation on finance.account_mapping
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
