-- The channel layer: WhatsApp as a channel, message templates and their approval, each person's channel and quiet-hours
-- preferences, the 24-hour customer-service window, and verified WhatsApp numbers for people who reply to act.

-- A message may be built from a template (with its variables in `payload`), say what it is for, and name the people-
-- facing language. `user_id` (already there) is the staff member it was meant for.
alter table kernel.notification add column kind text;
alter table kernel.notification add column language text;
create index notification_ix3 on kernel.notification (tenant_id, provider, provider_ref) where provider_ref is not null;

create table kernel.message_template (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  company_id uuid not null references kernel.company(id),
  code text not null,
  channel text not null check (channel in ('whatsapp', 'sms', 'email')),
  language text not null,
  category text not null default 'utility',
  body text not null,
  variables jsonb not null default '[]',
  buttons jsonb not null default '[]',
  status text not null default 'draft' check (status in ('draft', 'submitted', 'approved', 'rejected')),
  provider text,
  provider_template_id text,
  rejection_reason text,
  submitted_at timestamptz,
  decided_at timestamptz,
  unique (tenant_id, company_id, code, channel, language)
);
comment on table kernel.message_template is 'A named message with variables, per channel and language, and where it stands with the channel provider (WhatsApp needs approval before a template may start a conversation).';
alter table kernel.message_template enable row level security;
alter table kernel.message_template force row level security;
create policy tenant_isolation on kernel.message_template
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.user_notification_pref (
  tenant_id uuid not null references kernel.tenant(id),
  user_id uuid not null references kernel.app_user(id),
  updated_at timestamptz not null default now(),
  channels jsonb not null default '{}',
  quiet_enabled boolean not null default false,
  quiet_start time not null default '21:00',
  quiet_end time not null default '07:00',
  quiet_critical_ok boolean not null default false,
  language text not null default 'en',
  primary key (tenant_id, user_id)
);
comment on table kernel.user_notification_pref is 'Per person: which channel for which kind of message (alerts, brief, approvals), quiet hours in the company time zone, and language.';
alter table kernel.user_notification_pref enable row level security;
alter table kernel.user_notification_pref force row level security;
create policy tenant_isolation on kernel.user_notification_pref
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

create table kernel.contact_window (
  tenant_id uuid not null references kernel.tenant(id),
  company_id uuid not null references kernel.company(id),
  channel text not null,
  contact text not null,
  last_inbound_at timestamptz not null,
  primary key (tenant_id, company_id, channel, contact)
);
comment on table kernel.contact_window is 'When a contact last wrote to the business on a channel: free-form WhatsApp messages may be sent for 24 hours after.';
alter table kernel.contact_window enable row level security;
alter table kernel.contact_window force row level security;
create policy tenant_isolation on kernel.contact_window
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());

-- Verified WhatsApp numbers: a number counts only after its owner typed back the code sent to it, and only one person in
-- the business may hold a verified number (so a reply can be matched to exactly one user).
alter table kernel.user_phone drop constraint if exists user_phone_tenant_id_phone_key;
create unique index user_phone_verified on kernel.user_phone (tenant_id, phone) where verified_at is not null;
create index user_phone_ix1 on kernel.user_phone (tenant_id, user_id);
alter table kernel.user_phone add column code_hash text;
alter table kernel.user_phone add column code_expires_at timestamptz;
alter table kernel.user_phone add column attempts integer not null default 0;
