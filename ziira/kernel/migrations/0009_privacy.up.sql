-- Data protection: tracked data subject requests (access, correction, erasure), and the room the retention job needs to
-- mask old notifications. Nothing here names a country: how long things are kept is a company setting.

create table kernel.privacy_request (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  number text not null,
  request_type text not null check (request_type in ('access', 'correction', 'erasure')),
  subject text not null,
  subject_masked text not null,
  status text not null default 'open' check (status in ('open', 'in_progress', 'completed', 'refused')),
  received_on date not null default current_date,
  due_date date not null,
  handled_by uuid references kernel.app_user(id),
  notes text,
  found jsonb not null default '[]',
  erase_plan jsonb,
  outcome jsonb,
  completed_at timestamptz,
  unique (company_id, number)
);
comment on table kernel.privacy_request is 'A data subject request: a person asks what is held about them, to correct it, or to erase it.';
comment on column kernel.privacy_request.subject is 'What the person gave us to find them by; replaced by subject_masked once an erasure completes.';
comment on column kernel.privacy_request.found is 'What the search found: source, kind, record id, label, match (exact/possible).';
comment on column kernel.privacy_request.erase_plan is 'An erasure waiting for a second person''s approval: reason and the records chosen.';
comment on column kernel.privacy_request.outcome is 'What was exported or changed, what was kept and why.';
create index privacy_request_ix1 on kernel.privacy_request (tenant_id, status, due_date);
alter table kernel.privacy_request enable row level security;
alter table kernel.privacy_request force row level security;
create policy tenant_isolation on kernel.privacy_request
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- A notification is a record that cannot be edited (0005). The one allowed change is redaction: the retention job (or an
-- erasure) replaces the recipient, subject and body once, and marks the row. A redacted row cannot be changed again.
alter table kernel.notification add column redacted_at timestamptz;
create or replace function kernel.protect_notification() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Notifications are a record and cannot be deleted' using errcode = '23000';
  end if;
  if old.recipient is not null and (new.channel, new.recipient, new.subject, new.body, new.company_id)
     is distinct from (old.channel, old.recipient, old.subject, old.body, old.company_id) then
    if old.redacted_at is null and new.redacted_at is not null
       and (new.channel, new.company_id) is not distinct from (old.channel, old.company_id) then
      return new;
    end if;
    raise exception 'A notification cannot be edited after it is queued' using errcode = '23000';
  end if;
  if old.redacted_at is not null and new.redacted_at is distinct from old.redacted_at then
    raise exception 'A notification cannot be edited after it is queued' using errcode = '23000';
  end if;
  return new;
end $$;
