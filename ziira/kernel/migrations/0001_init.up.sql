-- Ziira Core 1.0 · schema 'kernel' (Kernel) · install migration
-- Requires: nothing
-- Platform tables. Always installed; cannot be removed.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists kernel;

create or replace function kernel.current_tenant() returns uuid
  language sql stable as $$ select nullif(current_setting('app.tenant_id', true), '')::uuid $$;
comment on function kernel.current_tenant() is 'Tenant of the current connection; set with SET app.tenant_id';

create or replace function kernel.forbid_change() returns trigger
  language plpgsql as $$
begin
  raise exception '% on %.% is not allowed: records are immutable; post a reversing document instead',
    tg_op, tg_table_schema, tg_table_name;
end $$;


create table kernel.tenant (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  status text not null default 'active' check (status in ('active', 'suspended', 'closed')),
  created_at timestamptz not null default now()
);
comment on table kernel.tenant is 'A customer account.';

create table kernel.app_user (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  email text,
  phone text,
  full_name text not null,
  password_hash text,
  mfa_enabled boolean not null default false,
  status text not null default 'active' check (status in ('invited', 'active', 'disabled')),
  last_login_at timestamptz,
  unique (tenant_id, email),
  unique (tenant_id, phone)
);
comment on table kernel.app_user is 'A person who can sign in.';
alter table kernel.app_user enable row level security;
alter table kernel.app_user force row level security;
create policy tenant_isolation on kernel.app_user
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.company (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  name text not null,
  kra_pin text,
  vat_registered boolean not null default false,
  base_currency char(3) not null default 'KES',
  fiscal_year_start_month smallint not null default 1 check (fiscal_year_start_month between 1 and 12),
  costing_method text not null default 'weighted_average' check (costing_method in ('weighted_average')),
  settings jsonb not null default '{}'
);
comment on table kernel.company is 'Legal entity with its own books.';
comment on column kernel.company.settings is 'Policies: negative stock, discount limits, etc.';
alter table kernel.company enable row level security;
alter table kernel.company force row level security;
create policy tenant_isolation on kernel.company
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.branch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  code text not null,
  name text not null,
  address text,
  phone text,
  is_active boolean not null default true,
  unique (company_id, code)
);
comment on table kernel.branch is 'An outlet or site of a company.';
comment on column kernel.branch.code is 'Short code used in document numbers, e.g. THK';
alter table kernel.branch enable row level security;
alter table kernel.branch force row level security;
create policy tenant_isolation on kernel.branch
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.unit (
  name text primary key,
  kind text not null check (kind in ('module', 'plugin')),
  version text not null,
  manifest jsonb not null,
  installed_at timestamptz not null default now()
);
comment on table kernel.unit is 'Installed modules and plugins (platform level).';

create table kernel.tenant_unit (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  unit_name text not null references kernel.unit(name),
  status text not null check (status in ('enabled', 'disabled')),
  settings jsonb not null default '{}',
  enabled_at timestamptz,
  disabled_at timestamptz,
  unique (tenant_id, unit_name)
);
comment on table kernel.tenant_unit is 'Which units each tenant has enabled.';
alter table kernel.tenant_unit enable row level security;
alter table kernel.tenant_unit force row level security;
create policy tenant_isolation on kernel.tenant_unit
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.permission (
  code text primary key,
  unit_name text not null references kernel.unit(name),
  description text not null
);
comment on table kernel.permission is 'Permission codes declared by units (platform level).';
comment on column kernel.permission.code is 'e.g. stock.adjust';

create table kernel.role (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  name text not null,
  is_system boolean not null default false,
  unique (tenant_id, name)
);
comment on table kernel.role is 'Named set of permissions.';
comment on column kernel.role.is_system is 'Default roles that cannot be deleted';
alter table kernel.role enable row level security;
alter table kernel.role force row level security;
create policy tenant_isolation on kernel.role
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.role_permission (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  role_id uuid not null references kernel.role(id) on delete cascade,
  permission_code text not null references kernel.permission(code),
  unique (role_id, permission_code)
);
comment on table kernel.role_permission is 'Permissions in a role.';
alter table kernel.role_permission enable row level security;
alter table kernel.role_permission force row level security;
create policy tenant_isolation on kernel.role_permission
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.user_role (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  user_id uuid not null references kernel.app_user(id),
  role_id uuid not null references kernel.role(id),
  company_id uuid references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  scope text not null default 'branch' check (scope in ('tenant', 'company', 'branch', 'own')),
  unique (user_id, role_id, company_id, branch_id)
);
comment on table kernel.user_role is 'Role granted to a user with a scope.';
comment on column kernel.user_role.company_id is 'Null = all companies';
comment on column kernel.user_role.branch_id is 'Null = all branches in scope';
alter table kernel.user_role enable row level security;
alter table kernel.user_role force row level security;
create policy tenant_isolation on kernel.user_role
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.user_phone (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  user_id uuid not null references kernel.app_user(id),
  phone text not null,
  verified_at timestamptz,
  unique (tenant_id, phone)
);
comment on table kernel.user_phone is 'Verified phone numbers for WhatsApp.';
alter table kernel.user_phone enable row level security;
alter table kernel.user_phone force row level security;
create policy tenant_isolation on kernel.user_phone
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.api_key (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  name text not null,
  key_hash text not null unique,
  scopes text[] not null default '{}',
  expires_at timestamptz,
  revoked_at timestamptz
);
comment on table kernel.api_key is 'Keys for server-to-server integrations.';
alter table kernel.api_key enable row level security;
alter table kernel.api_key force row level security;
create policy tenant_isolation on kernel.api_key
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.document_series (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  doc_type text not null,
  prefix text not null,
  next_number bigint not null default 1,
  padding smallint not null default 6,
  unique (company_id, branch_id, doc_type)
);
comment on table kernel.document_series is 'Numbering per document type and branch.';
comment on column kernel.document_series.doc_type is 'e.g. sale, invoice, po';
comment on column kernel.document_series.prefix is 'e.g. INV-THK-';
alter table kernel.document_series enable row level security;
alter table kernel.document_series force row level security;
create policy tenant_isolation on kernel.document_series
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.reason_code (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  category text not null,
  code text not null,
  label text not null,
  requires_note boolean not null default false,
  is_active boolean not null default true,
  unique (tenant_id, category, code)
);
comment on table kernel.reason_code is 'Managed list of reasons for voids, adjustments, etc.';
comment on column kernel.reason_code.category is 'void, refund, discount, price_override, stock_adjustment, write_off, transfer_variance, till_variance';
alter table kernel.reason_code enable row level security;
alter table kernel.reason_code force row level security;
create policy tenant_isolation on kernel.reason_code
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.approval_rule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  doc_type text not null,
  min_amount numeric(18,2) not null default 0,
  max_amount numeric(18,2),
  step smallint not null default 1,
  approver_role_id uuid not null references kernel.role(id),
  forbid_creator boolean not null default true,
  is_active boolean not null default true
);
comment on table kernel.approval_rule is 'The approval matrix.';
comment on column kernel.approval_rule.max_amount is 'Null = no upper limit';
comment on column kernel.approval_rule.forbid_creator is 'Separation of duties';
alter table kernel.approval_rule enable row level security;
alter table kernel.approval_rule force row level security;
create policy tenant_isolation on kernel.approval_rule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.approval_request (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  rule_id uuid references kernel.approval_rule(id),
  doc_type text not null,
  doc_id uuid not null,
  step smallint not null default 1,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
  requested_by uuid references kernel.app_user(id),
  decided_by uuid references kernel.app_user(id),
  decided_at timestamptz,
  channel text check (channel in ('web', 'pos', 'whatsapp', 'api')),
  note text,
  expires_at timestamptz
);
comment on table kernel.approval_request is 'An approval waiting for or given a decision.';
create index approval_request_ix1 on kernel.approval_request (tenant_id, status);
create index approval_request_ix2 on kernel.approval_request (doc_type, doc_id);
alter table kernel.approval_request enable row level security;
alter table kernel.approval_request force row level security;
create policy tenant_isolation on kernel.approval_request
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.workflow_rule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  name text not null,
  version integer not null default 1,
  trigger jsonb not null,
  conditions jsonb not null default '[]',
  actions jsonb not null,
  is_active boolean not null default true
);
comment on table kernel.workflow_rule is 'Automation rules: trigger, conditions, actions.';
comment on column kernel.workflow_rule.trigger is 'Event type or schedule';
alter table kernel.workflow_rule enable row level security;
alter table kernel.workflow_rule force row level security;
create policy tenant_isolation on kernel.workflow_rule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.workflow_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  rule_id uuid not null references kernel.workflow_rule(id),
  event_id bigint,
  status text not null check (status in ('succeeded', 'failed', 'skipped')),
  result jsonb
);
comment on table kernel.workflow_run is 'Each execution of a rule.';
alter table kernel.workflow_run enable row level security;
alter table kernel.workflow_run force row level security;
create policy tenant_isolation on kernel.workflow_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.event_outbox (
  id bigint generated always as identity primary key,
  tenant_id uuid not null references kernel.tenant(id),
  event_type text not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  attempts integer not null default 0
);
comment on table kernel.event_outbox is 'Domain events written in the same transaction as the change.';
comment on column kernel.event_outbox.event_type is 'e.g. sale.posted';
create index event_outbox_ix1 on kernel.event_outbox (published_at) where published_at is null;
alter table kernel.event_outbox enable row level security;
alter table kernel.event_outbox force row level security;
create policy tenant_isolation on kernel.event_outbox
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.audit_log (
  id bigint generated always as identity primary key,
  tenant_id uuid not null references kernel.tenant(id),
  occurred_at timestamptz not null default now(),
  user_id uuid references kernel.app_user(id),
  channel text not null check (channel in ('web', 'pos', 'api', 'whatsapp', 'system', 'import')),
  device_id uuid,
  ip_address inet,
  action text not null,
  entity_type text not null,
  entity_id uuid,
  changes jsonb,
  prev_hash text,
  hash text not null
);
comment on table kernel.audit_log is 'Append-only audit trail with hash chain.';
comment on column kernel.audit_log.action is 'e.g. create, update, approve, post, void, login';
comment on column kernel.audit_log.changes is 'Previous and new values';
create index audit_log_ix1 on kernel.audit_log (tenant_id, entity_type, entity_id);
create index audit_log_ix2 on kernel.audit_log (tenant_id, occurred_at);
alter table kernel.audit_log enable row level security;
alter table kernel.audit_log force row level security;
create policy tenant_isolation on kernel.audit_log
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger audit_log_immutable before update or delete on kernel.audit_log
  for each row execute function kernel.forbid_change();

create table kernel.idempotency_key (
  tenant_id uuid not null references kernel.tenant(id),
  key text not null,
  request_hash text not null,
  response jsonb,
  created_at timestamptz not null default now(),
  primary key (tenant_id, key)
);
comment on table kernel.idempotency_key is 'Prevents duplicate creates on retry.';
alter table kernel.idempotency_key enable row level security;
alter table kernel.idempotency_key force row level security;
create policy tenant_isolation on kernel.idempotency_key
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.file (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  storage_key text not null unique,
  filename text not null,
  content_type text not null,
  size_bytes bigint not null
);
comment on table kernel.file is 'Uploaded or generated files.';
alter table kernel.file enable row level security;
alter table kernel.file force row level security;
create policy tenant_isolation on kernel.file
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.notification (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  user_id uuid references kernel.app_user(id),
  channel text not null check (channel in ('whatsapp', 'sms', 'email', 'in_app')),
  template text not null,
  payload jsonb not null default '{}',
  status text not null default 'queued' check (status in ('queued', 'sent', 'delivered', 'read', 'failed')),
  provider_message_id text,
  sent_at timestamptz
);
comment on table kernel.notification is 'Messages sent to users.';
alter table kernel.notification enable row level security;
alter table kernel.notification force row level security;
create policy tenant_isolation on kernel.notification
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.integration_credential (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  provider text not null check (provider in ('daraja', 'bank', 'etims', 'whatsapp', 'email', 'sms')),
  label text not null,
  secret_ciphertext bytea not null,
  config jsonb not null default '{}',
  status text not null default 'active' check (status in ('active', 'disabled'))
);
comment on table kernel.integration_credential is 'Encrypted credentials for Daraja, banks, eTIMS, WhatsApp.';
comment on column kernel.integration_credential.secret_ciphertext is 'Encrypted; never logged';
comment on column kernel.integration_credential.config is 'Non-secret settings, e.g. shortcode';
alter table kernel.integration_credential enable row level security;
alter table kernel.integration_credential force row level security;
create policy tenant_isolation on kernel.integration_credential
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.integration_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  provider text not null,
  direction text not null check (direction in ('inbound', 'outbound')),
  operation text not null,
  status text not null check (status in ('ok', 'error', 'retrying')),
  related_type text,
  related_id uuid,
  error text,
  duration_ms integer
);
comment on table kernel.integration_log is 'Calls to and from external systems.';
create index integration_log_ix1 on kernel.integration_log (tenant_id, provider, created_at);
alter table kernel.integration_log enable row level security;
alter table kernel.integration_log force row level security;
create policy tenant_isolation on kernel.integration_log
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.etims_device (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  device_serial text not null,
  registration jsonb not null default '{}',
  status text not null default 'active' check (status in ('pending', 'active', 'inactive')),
  unique (branch_id, device_serial)
);
comment on table kernel.etims_device is 'eTIMS registration per branch.';
alter table kernel.etims_device enable row level security;
alter table kernel.etims_device force row level security;
create policy tenant_isolation on kernel.etims_device
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table kernel.etims_submission (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  etims_device_id uuid not null references kernel.etims_device(id),
  doc_type text not null check (doc_type in ('sale', 'invoice', 'credit_note', 'purchase')),
  doc_id uuid not null,
  status text not null default 'pending' check (status in ('pending', 'submitted', 'failed')),
  attempts integer not null default 0,
  kra_invoice_no text,
  signature text,
  qr_data text,
  submitted_at timestamptz,
  last_error text,
  unique (doc_type, doc_id)
);
comment on table kernel.etims_submission is 'Submission of a sales or credit document to KRA eTIMS.';
create index etims_submission_ix1 on kernel.etims_submission (tenant_id, status);
alter table kernel.etims_submission enable row level security;
alter table kernel.etims_submission force row level security;
create policy tenant_isolation on kernel.etims_submission
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

