-- Ziira Core · schema 'jobs' · 0005 · workshop floor: mechanic timers, vehicle inspection, deposits applied to the invoice,
-- storage billed after invoicing, and a job made from a booked appointment.

alter table jobs.job
  add column deposit_applied numeric(18,2) not null default 0 check (deposit_applied >= 0),
  add column storage_invoice_id uuid,
  add column storage_invoice_number text,
  add column appointment_id uuid;
comment on column jobs.job.deposit_applied is 'How much of the deposit has been set against the job''s invoice (the rest stays on the customer''s account).';
comment on column jobs.job.storage_invoice_id is 'A second, small invoice for storage that ran after the main invoice was made.';
comment on column jobs.job.appointment_id is 'The booked appointment this job was made from; a plain id into the bookings unit.';

create table jobs.job_timer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  user_id uuid not null references kernel.app_user(id),
  started_at timestamptz not null default now(),
  stopped_at timestamptz,
  labour_id uuid,
  note text
);
comment on table jobs.job_timer is 'A mechanic''s running clock on a job. Stopping it puts the time worked on the job as a labour line.';
create unique index job_timer_one_running_ix on jobs.job_timer (user_id) where stopped_at is null;
create index job_timer_ix1 on jobs.job_timer (job_id);

create table jobs.job_inspection_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  job_id uuid not null references jobs.job(id),
  section text not null,
  label text not null,
  rating text not null default 'pending' check (rating in ('pending', 'green', 'amber', 'red', 'na')),
  note text,
  position integer not null default 0
);
comment on table jobs.job_inspection_item is 'One line of the vehicle health check: green (good), amber (will need attention soon), red (needs attention now).';
create index job_inspection_item_ix1 on jobs.job_inspection_item (job_id, position);

do $$
declare t text;
begin
  foreach t in array array['job_timer', 'job_inspection_item']
  loop
    execute format('alter table jobs.%I enable row level security', t);
    execute format('alter table jobs.%I force row level security', t);
    execute format('create policy tenant_isolation on jobs.%I using (tenant_id = kernel.current_tenant()) '
                   'with check (tenant_id = kernel.current_tenant())', t);
  end loop;
end $$;
