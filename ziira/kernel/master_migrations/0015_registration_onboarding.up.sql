-- Onboarding answers given at sign-up (data only: used for hints, never for rules) and the setup steps that failed
-- after a business was created, so they can be repaired later without losing the business.

alter table master.registration add column phone text;
alter table master.registration add column owner_role text;
alter table master.registration add column business_size text;
alter table master.registration add column staff_size text;
alter table master.registration add column business_type text;
alter table master.registration add column plan_code text;
comment on column master.registration.plan_code is 'A public plan the person arrived from (a link on the website); only used when it is still public at verification, else the default plan applies.';
comment on column master.registration.owner_role is 'owner, manager, accountant or other: onboarding hints only.';

alter table master.tenant add column onboarding jsonb;
comment on column master.tenant.onboarding is 'What the owner said at sign-up (role, phone, branches, staff, kind of business): onboarding hints only.';

create table master.registration_repair (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references master.tenant (id) on delete cascade,
  registration_id uuid,
  step text not null check (step in ('pack', 'plan')),
  detail jsonb not null default '{}'::jsonb,
  error text,
  attempts int not null default 1,
  created_at timestamptz not null default now(),
  last_attempt_at timestamptz not null default now(),
  resolved_at timestamptz
);
create unique index registration_repair_open_ix on master.registration_repair (tenant_id, step) where resolved_at is null;
comment on table master.registration_repair is 'An optional setup step (country pack, trial plan) that failed when a business registered. The business exists and works; the worker retries the step until it succeeds.';
