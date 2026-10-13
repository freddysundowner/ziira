-- Recurring tasks (expire old quotations, chase overdue invoices) and the notification queue (messages to customers by
-- email, SMS or WhatsApp, with who asked not to be contacted).

create table kernel.periodic_run (
  tenant_id uuid not null references kernel.tenant(id),
  name text not null,
  last_run_at timestamptz not null,
  last_error text,
  primary key (tenant_id, name)
);
comment on table kernel.periodic_run is 'When each recurring task last ran for the business.';
alter table kernel.periodic_run enable row level security;
alter table kernel.periodic_run force row level security;
create policy tenant_isolation on kernel.periodic_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- The notification table from the first schema held messages "to users"; it was never used. It now records every message
-- sent to a person outside the system (a customer, a supplier) and what became of it.
alter table kernel.notification add column company_id uuid references kernel.company(id);
alter table kernel.notification add column recipient text;
alter table kernel.notification add column subject text;
alter table kernel.notification add column body text;
alter table kernel.notification add column attempts integer not null default 0;
alter table kernel.notification add column provider text;
alter table kernel.notification add column error text;
alter table kernel.notification add column ref_type text;
alter table kernel.notification add column ref_id uuid;
alter table kernel.notification add column dedupe_key text;
alter table kernel.notification rename column provider_message_id to provider_ref;
alter table kernel.notification alter column template drop not null;
alter table kernel.notification drop constraint notification_status_check;
alter table kernel.notification add constraint notification_status_check
  check (status in ('queued', 'sent', 'delivered', 'read', 'failed', 'skipped'));
create unique index notification_dedupe on kernel.notification (tenant_id, dedupe_key) where dedupe_key is not null;
create index notification_ix1 on kernel.notification (tenant_id, status, created_at);
create index notification_ix2 on kernel.notification (ref_type, ref_id);
create function kernel.protect_notification() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Notifications are a record and cannot be deleted' using errcode = '23000';
  end if;
  if old.recipient is not null and (new.channel, new.recipient, new.subject, new.body, new.company_id)
     is distinct from (old.channel, old.recipient, old.subject, old.body, old.company_id) then
    raise exception 'A notification cannot be edited after it is queued' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger notification_protected before update or delete on kernel.notification
  for each row execute function kernel.protect_notification();

create table kernel.notification_optout (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  recipient text not null,
  channel text,
  reason text,
  unique (tenant_id, company_id, recipient, channel)
);
comment on table kernel.notification_optout is 'People who asked not to be contacted (channel null: on any channel).';
alter table kernel.notification_optout enable row level security;
alter table kernel.notification_optout force row level security;
create policy tenant_isolation on kernel.notification_optout
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
