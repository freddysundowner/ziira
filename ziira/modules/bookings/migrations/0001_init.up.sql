-- Ziira Core · schema 'bookings' (Appointments and Bookings) · install migration
-- Requires: kernel, products (service items are soft references)
-- Resources and their hours, service offers, appointments (double booking is impossible: an exclusion constraint per
-- resource), waitlist, class attendees and the booking settings of each company.

create extension if not exists btree_gist;
create schema if not exists bookings;

create table bookings.booking_settings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id) unique,
  online_enabled boolean not null default false,
  slug text,
  auto_confirm boolean not null default false,
  min_notice_minutes integer not null default 120 check (min_notice_minutes >= 0),
  max_days_ahead integer not null default 60 check (max_days_ahead between 1 and 365),
  cancel_window_hours integer not null default 24 check (cancel_window_hours >= 0),
  reminders_enabled boolean not null default true,
  reminder_hours_before integer not null default 24 check (reminder_hours_before between 1 and 168),
  slot_granularity_minutes integer not null default 15 check (slot_granularity_minutes in (5, 10, 15, 20, 30, 60)),
  default_buffer_minutes integer not null default 0 check (default_buffer_minutes between 0 and 240),
  show_resources_publicly boolean not null default false,
  invoice_on_completion boolean not null default false,
  invoice_due_days integer check (invoice_due_days is null or invoice_due_days between 0 and 365),
  quiet_start time not null default '21:00',
  quiet_end time not null default '07:00',
  consent_text text,
  public_name text,
  public_note text
);
comment on table bookings.booking_settings is 'Booking policy of a company (one row).';
alter table bookings.booking_settings enable row level security;
alter table bookings.booking_settings force row level security;
create policy tenant_isolation on bookings.booking_settings
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.resource (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  name text not null,
  kind text not null default 'staff' check (kind in ('staff', 'room', 'chair', 'equipment')),
  user_id uuid references kernel.app_user(id),
  colour text,
  note text,
  show_publicly boolean not null default true,
  sort_order integer not null default 0,
  is_active boolean not null default true
);
comment on table bookings.resource is 'Something that can be booked: a person, a room, a chair, a machine.';
alter table bookings.resource enable row level security;
alter table bookings.resource force row level security;
create policy tenant_isolation on bookings.resource
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.resource_hours (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  resource_id uuid not null references bookings.resource(id) on delete cascade,
  weekday smallint not null check (weekday between 0 and 6),
  start_time time not null,
  end_time time not null,
  check (end_time > start_time)
);
comment on table bookings.resource_hours is 'Weekly working hours of a resource (several rows a day allow a break). Monday is 0.';
alter table bookings.resource_hours enable row level security;
alter table bookings.resource_hours force row level security;
create policy tenant_isolation on bookings.resource_hours
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.resource_time_off (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  resource_id uuid not null references bookings.resource(id) on delete cascade,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  reason text,
  check (ends_at > starts_at)
);
comment on table bookings.resource_time_off is 'A period when a resource cannot be booked (leave, repairs).';
alter table bookings.resource_time_off enable row level security;
alter table bookings.resource_time_off force row level security;
create policy tenant_isolation on bookings.resource_time_off
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.service_offer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  product_id uuid,
  name text not null,
  description text,
  kind text not null default 'appointment' check (kind in ('appointment', 'class')),
  duration_minutes integer not null check (duration_minutes between 5 and 1440),
  buffer_before_minutes integer not null default 0 check (buffer_before_minutes between 0 and 240),
  buffer_after_minutes integer not null default 0 check (buffer_after_minutes between 0 and 240),
  price numeric(18,2) not null default 0 check (price >= 0),
  resource_mode text not null default 'any' check (resource_mode in ('any', 'all')),
  capacity integer not null default 1 check (capacity between 1 and 500),
  show_publicly boolean not null default true,
  is_active boolean not null default true
);
comment on table bookings.service_offer is 'A bookable service: how long it takes, what it costs, who can do it.';
alter table bookings.service_offer enable row level security;
alter table bookings.service_offer force row level security;
create policy tenant_isolation on bookings.service_offer
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.service_offer_resource (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  offer_id uuid not null references bookings.service_offer(id) on delete cascade,
  resource_id uuid not null references bookings.resource(id) on delete cascade,
  unique (offer_id, resource_id)
);
comment on table bookings.service_offer_resource is 'Which resources can do a service.';
alter table bookings.service_offer_resource enable row level security;
alter table bookings.service_offer_resource force row level security;
create policy tenant_isolation on bookings.service_offer_resource
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.appointment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  offer_id uuid not null references bookings.service_offer(id),
  kind text not null default 'appointment' check (kind in ('appointment', 'class')),
  capacity integer not null default 1 check (capacity >= 1),
  status text not null default 'confirmed' check (status in
    ('requested', 'confirmed', 'checked_in', 'in_service', 'completed', 'cancelled', 'no_show')),
  source text not null default 'staff' check (source in ('staff', 'online', 'walk_in', 'waitlist', 'recurring')),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  customer_id uuid,
  client_name text,
  client_phone text,
  client_email text,
  price numeric(18,2) not null default 0 check (price >= 0),
  note text,
  series_id uuid,
  series_index integer,
  local_id text,
  cancel_reason_id uuid,
  cancel_note text,
  cancelled_at timestamptz,
  cancelled_by uuid,
  late_cancellation boolean not null default false,
  checked_in_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  minutes_worked integer,
  invoice_id uuid,
  invoice_number text,
  deposit_amount numeric(18,2) not null default 0 check (deposit_amount >= 0),
  consent_given_at timestamptz,
  unique (company_id, number),
  check (ends_at > starts_at)
);
comment on table bookings.appointment is 'A booking of a client for a service (or a class with several attendees).';
alter table bookings.appointment enable row level security;
alter table bookings.appointment force row level security;
create policy tenant_isolation on bookings.appointment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create unique index appointment_local_id_ux on bookings.appointment (company_id, local_id) where local_id is not null;
create index appointment_start_ix on bookings.appointment (company_id, starts_at);
create index appointment_customer_ix on bookings.appointment (customer_id) where customer_id is not null;
create index appointment_series_ix on bookings.appointment (series_id) where series_id is not null;

create table bookings.appointment_resource (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  appointment_id uuid not null references bookings.appointment(id) on delete cascade,
  resource_id uuid not null references bookings.resource(id),
  blocked tstzrange not null,
  holds boolean not null default true,
  unique (appointment_id, resource_id),
  constraint no_double_booking exclude using gist (resource_id with =, blocked with &&) where (holds)
);
comment on table bookings.appointment_resource is 'A resource held by an appointment. The exclusion constraint makes double booking impossible.';
alter table bookings.appointment_resource enable row level security;
alter table bookings.appointment_resource force row level security;
create policy tenant_isolation on bookings.appointment_resource
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index appointment_resource_res_ix on bookings.appointment_resource using gist (resource_id, blocked);

create table bookings.appointment_attendee (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  appointment_id uuid not null references bookings.appointment(id) on delete cascade,
  customer_id uuid,
  name text not null,
  phone text,
  email text,
  status text not null default 'booked' check (status in ('booked', 'attended', 'no_show', 'cancelled'))
);
comment on table bookings.appointment_attendee is 'A person booked on a class.';
alter table bookings.appointment_attendee enable row level security;
alter table bookings.appointment_attendee force row level security;
create policy tenant_isolation on bookings.appointment_attendee
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.appointment_message (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  appointment_id uuid not null references bookings.appointment(id) on delete cascade,
  kind text not null check (kind in ('confirmation', 'reminder', 'cancelled')),
  queued_at timestamptz not null default now(),
  unique (appointment_id, kind)
);
comment on table bookings.appointment_message is 'Which reminder or confirmation was queued for an appointment (once per kind).';
alter table bookings.appointment_message enable row level security;
alter table bookings.appointment_message force row level security;
create policy tenant_isolation on bookings.appointment_message
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.waitlist_entry (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  offer_id uuid not null references bookings.service_offer(id),
  resource_id uuid references bookings.resource(id),
  customer_id uuid,
  client_name text not null,
  client_phone text,
  client_email text,
  wanted_from date not null,
  wanted_to date not null,
  note text,
  status text not null default 'waiting' check (status in ('waiting', 'offered', 'booked', 'removed')),
  offered_starts_at timestamptz,
  offered_resource_id uuid references bookings.resource(id),
  offered_at timestamptz,
  appointment_id uuid,
  check (wanted_to >= wanted_from)
);
comment on table bookings.waitlist_entry is 'A client waiting for an earlier or different slot.';
alter table bookings.waitlist_entry enable row level security;
alter table bookings.waitlist_entry force row level security;
create policy tenant_isolation on bookings.waitlist_entry
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table bookings.booking_refusal (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  resource_id uuid references bookings.resource(id),
  attempted_start timestamptz not null,
  source text not null default 'staff',
  reason text not null default 'conflict'
);
comment on table bookings.booking_refusal is 'A booking that was refused because the time was taken (kept for Intelligence).';
alter table bookings.booking_refusal enable row level security;
alter table bookings.booking_refusal force row level security;
create policy tenant_isolation on bookings.booking_refusal
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index booking_refusal_ix on bookings.booking_refusal (company_id, created_at);
