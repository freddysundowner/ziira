-- Lead Intel connections (one WhatsApp number or SMS line per business), the webhook events already seen, and the messages
-- people sent to the business. The keys live in the credential store, never here.
create schema if not exists plg_leadsintel;
comment on schema plg_leadsintel is 'Lead Intel messaging plugin (WhatsApp and SMS)';

create table plg_leadsintel.connection (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  company_id uuid not null references kernel.company(id),
  kind text not null check (kind in ('whatsapp', 'sms')),
  external_connection_id text not null,
  token_hash text not null,
  status text not null default 'requested'
    check (status in ('requested', 'awaiting_code', 'code_sent', 'connected', 'active', 'failed', 'cancelled', 'disconnected')),
  request_id text,
  claim_id text,
  display_phone text,
  phone_number_id text,
  error_code text,
  error_message text,
  last_checked_at timestamptz,
  unique (tenant_id, external_connection_id),
  unique (token_hash)
);
comment on table plg_leadsintel.connection is 'A WhatsApp number or SMS line a business connected through Lead Intel, and where its setup stands. token_hash identifies the business''s inbound webhook address.';
create index leadsintel_connection_ix1 on plg_leadsintel.connection (tenant_id, company_id, kind, created_at desc);
alter table plg_leadsintel.connection enable row level security;
alter table plg_leadsintel.connection force row level security;
create policy tenant_isolation on plg_leadsintel.connection
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table plg_leadsintel.inbound_event (
  tenant_id uuid not null references kernel.tenant(id),
  event_id text not null,
  received_at timestamptz not null default now(),
  primary key (tenant_id, event_id)
);
comment on table plg_leadsintel.inbound_event is 'Webhook deliveries already processed (X-LeadIntel-Event-Id), so a retry does nothing twice.';
alter table plg_leadsintel.inbound_event enable row level security;
alter table plg_leadsintel.inbound_event force row level security;
create policy tenant_isolation on plg_leadsintel.inbound_event
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table plg_leadsintel.inbound_message (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  connection_id uuid references plg_leadsintel.connection(id),
  provider_message_id text not null,
  sender text not null,
  kind text not null,
  body text,
  button_id text,
  media jsonb,
  received_at timestamptz,
  outcome text not null,
  read_at timestamptz,
  unique (tenant_id, provider_message_id)
);
comment on table plg_leadsintel.inbound_message is 'What people wrote to the business (a customer''s reply to a reminder, a staff member''s command) and what was done with it. Replies from a number that is not a verified user are stored only.';
create index leadsintel_inbound_ix1 on plg_leadsintel.inbound_message (tenant_id, company_id, created_at desc);
create index leadsintel_inbound_ix2 on plg_leadsintel.inbound_message (tenant_id, sender, created_at desc);
alter table plg_leadsintel.inbound_message enable row level security;
alter table plg_leadsintel.inbound_message force row level security;
create policy tenant_isolation on plg_leadsintel.inbound_message
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
