-- Ziira Core · schema 'bookings' · wave 2: checkout, visits, group sessions, commission, recalls, fees, chair rental,
-- pack set-up. Additive only: nothing in 0001 is changed except new columns and one widened check.

alter table bookings.service_offer
  add column processing_start_minutes integer not null default 0 check (processing_start_minutes >= 0),
  add column processing_minutes integer not null default 0 check (processing_minutes >= 0),
  add column deposit_amount numeric(18,2) not null default 0 check (deposit_amount >= 0),
  add column deposit_percent numeric(5,2) not null default 0 check (deposit_percent between 0 and 100),
  add column recall_days integer check (recall_days is null or recall_days between 1 and 730),
  add column needs_patch_test boolean not null default false,
  add column price_is_example boolean not null default false,
  add column group_late_cancel_hours integer check (group_late_cancel_hours is null or group_late_cancel_hours >= 0),
  add constraint service_offer_processing_fits check (processing_start_minutes + processing_minutes <= duration_minutes);
comment on column bookings.service_offer.processing_minutes is
  'Minutes inside the service when the person serving is free (colour setting). The service starts processing after processing_start_minutes.';

alter table bookings.resource
  add column level text,
  add column is_template boolean not null default false;

alter table bookings.appointment
  add column visit_id uuid,
  add column deposit_paid numeric(18,2) not null default 0 check (deposit_paid >= 0),
  add column price_variant text,
  add column payer_customer_id uuid,
  add column payer_member_no text,
  add column preauth_ref text,
  add column copay_amount numeric(18,2) check (copay_amount is null or copay_amount >= 0),
  add column claim_id uuid;
create index appointment_visit_ix on bookings.appointment (visit_id) where visit_id is not null;

alter table bookings.appointment_attendee
  add column late_cancellation boolean not null default false,
  add column cancelled_at timestamptz,
  add column checked_in_at timestamptz,
  add column source text not null default 'staff',
  add column credit_ref text;
create unique index appointment_attendee_customer_ux on bookings.appointment_attendee (appointment_id, customer_id)
  where customer_id is not null and status <> 'cancelled';

alter table bookings.booking_settings
  add column late_cancel_fee_percent numeric(5,2) not null default 0 check (late_cancel_fee_percent between 0 and 100),
  add column no_show_fee_percent numeric(5,2) not null default 0 check (no_show_fee_percent between 0 and 100),
  add column waitlist_confirm_minutes integer not null default 30 check (waitlist_confirm_minutes between 0 and 1440),
  add column rebook_prompt_hours integer not null default 0 check (rebook_prompt_hours between 0 and 720),
  add column recalls_enabled boolean not null default true,
  add column deposit_note text,
  add column patch_test_valid_days integer check (patch_test_valid_days is null or patch_test_valid_days between 1 and 1000),
  add column commission_excludes_tax boolean not null default true,
  add column pack_name text,
  add column reminder_template text,
  add column recall_template text,
  add column rebook_template text,
  add column fee_product_id uuid,
  add column walkin_customer_id uuid,
  add column discount_limit_percent numeric(5,2) check (discount_limit_percent is null or discount_limit_percent between 0 and 100);

-- a few more kinds of message queued once per appointment
alter table bookings.appointment_message drop constraint appointment_message_kind_check;
alter table bookings.appointment_message add constraint appointment_message_kind_check
  check (kind in ('confirmation', 'reminder', 'cancelled', 'rebook', 'recall', 'deposit'));

-- a service with processing time holds its person in two stretches (before and after the free minutes)
alter table bookings.appointment_resource add column part smallint not null default 0;
alter table bookings.appointment_resource drop constraint appointment_resource_appointment_id_resource_id_key;
alter table bookings.appointment_resource add constraint appointment_resource_part_ux unique (appointment_id, resource_id, part);

create table bookings.price_variant (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  offer_id uuid not null references bookings.service_offer(id) on delete cascade,
  label text not null,
  level text,
  price numeric(18,2) not null check (price >= 0),
  sort_order integer not null default 0,
  is_active boolean not null default true
);
comment on table bookings.price_variant is 'A price of a service for a staff level or a variant such as hair length.';
alter table bookings.price_variant enable row level security;
alter table bookings.price_variant force row level security;
create policy tenant_isolation on bookings.price_variant
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index price_variant_offer_ix on bookings.price_variant (offer_id);

create table bookings.closed_day (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  day date not null,
  label text
);
comment on table bookings.closed_day is 'A day the business (or one branch) is closed: no sessions are booked on it.';
alter table bookings.closed_day enable row level security;
alter table bookings.closed_day force row level security;
create policy tenant_isolation on bookings.closed_day
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create unique index closed_day_ux on bookings.closed_day (company_id, day, coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid));

create table bookings.session_waitlist (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  appointment_id uuid not null references bookings.appointment(id) on delete cascade,
  customer_id uuid,
  name text not null,
  phone text,
  email text,
  status text not null default 'waiting' check (status in ('waiting', 'offered', 'promoted', 'expired', 'removed')),
  token text not null default replace(gen_random_uuid()::text, '-', ''),
  offered_at timestamptz,
  confirm_by timestamptz,
  attendee_id uuid,
  source text not null default 'staff'
);
comment on table bookings.session_waitlist is 'A person waiting for a place in a full group session. Offers hold a place until confirm_by.';
alter table bookings.session_waitlist enable row level security;
alter table bookings.session_waitlist force row level security;
create policy tenant_isolation on bookings.session_waitlist
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index session_waitlist_appt_ix on bookings.session_waitlist (appointment_id, status, created_at);
create unique index session_waitlist_token_ux on bookings.session_waitlist (token);
create unique index session_waitlist_customer_ux on bookings.session_waitlist (appointment_id, customer_id)
  where customer_id is not null and status in ('waiting', 'offered');

create table bookings.checkout (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  customer_id uuid,
  client_name text,
  visit_id uuid,
  status text not null default 'open' check (status in ('open', 'done', 'void')),
  note text,
  discount_kind text not null default 'amount' check (discount_kind in ('amount', 'percent')),
  discount_value numeric(18,2) not null default 0 check (discount_value >= 0),
  discount_reason_id uuid,
  discount_note text,
  payer_customer_id uuid,
  copay_amount numeric(18,2) check (copay_amount is null or copay_amount >= 0),
  preauth_ref text,
  subtotal numeric(18,2) not null default 0,
  discount_total numeric(18,2) not null default 0,
  credit_total numeric(18,2) not null default 0,
  total numeric(18,2) not null default 0,
  paid_total numeric(18,2) not null default 0,
  tip_total numeric(18,2) not null default 0,
  invoice_id uuid,
  invoice_number text,
  payer_invoice_id uuid,
  payer_invoice_number text,
  local_id text,
  completed_at timestamptz,
  completed_by uuid,
  voided_at timestamptz,
  void_reason text,
  unique (company_id, number)
);
comment on table bookings.checkout is 'One client''s bill at the front desk: services, products, discount, tip, credits and payments.';
alter table bookings.checkout enable row level security;
alter table bookings.checkout force row level security;
create policy tenant_isolation on bookings.checkout
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create unique index checkout_local_ux on bookings.checkout (company_id, local_id) where local_id is not null;
create index checkout_day_ix on bookings.checkout (company_id, completed_at);
create index checkout_visit_ix on bookings.checkout (visit_id) where visit_id is not null;

create table bookings.checkout_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  checkout_id uuid not null references bookings.checkout(id) on delete cascade,
  line_no integer not null,
  kind text not null check (kind in ('service', 'product', 'fee')),
  appointment_id uuid references bookings.appointment(id),
  offer_id uuid references bookings.service_offer(id),
  product_id uuid,
  fee_id uuid,
  description text not null,
  quantity numeric(18,4) not null default 1 check (quantity > 0),
  unit_price numeric(18,2) not null check (unit_price >= 0),
  discount numeric(18,2) not null default 0 check (discount >= 0),
  resource_id uuid references bookings.resource(id),
  variant text,
  credit_quantity numeric(18,4) not null default 0 check (credit_quantity >= 0),
  credit_ref text,
  unique (checkout_id, line_no)
);
comment on table bookings.checkout_line is 'A line of a checkout: a service, a retail product or a fee. The price is what the client pays for it.';
alter table bookings.checkout_line enable row level security;
alter table bookings.checkout_line force row level security;
create policy tenant_isolation on bookings.checkout_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index checkout_line_appt_ix on bookings.checkout_line (appointment_id) where appointment_id is not null;

create table bookings.checkout_payment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  checkout_id uuid not null references bookings.checkout(id) on delete cascade,
  kind text not null check (kind in ('payment', 'deposit', 'credit', 'tender')),
  method text not null,
  amount numeric(18,2) not null check (amount > 0),
  reference text,
  provider text,
  receipt_id uuid,
  receipt_number text
);
comment on table bookings.checkout_payment is 'Money or credit that paid a checkout: a payment, a deposit already held, a voucher, a package.';
alter table bookings.checkout_payment enable row level security;
alter table bookings.checkout_payment force row level security;
create policy tenant_isolation on bookings.checkout_payment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index checkout_payment_co_ix on bookings.checkout_payment (checkout_id);

create table bookings.checkout_tip (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  checkout_id uuid not null references bookings.checkout(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  resource_id uuid not null references bookings.resource(id),
  amount numeric(18,2) not null check (amount > 0),
  method text not null,
  held boolean not null default true,
  paid_out_at timestamptz,
  paid_out_by uuid
);
comment on table bookings.checkout_tip is 'A tip for a staff member. Not revenue: it is owed to the person until paid out.';
alter table bookings.checkout_tip enable row level security;
alter table bookings.checkout_tip force row level security;
create policy tenant_isolation on bookings.checkout_tip
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index checkout_tip_open_ix on bookings.checkout_tip (company_id, resource_id) where held and paid_out_at is null;

create table bookings.commission_rule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  applies_to text not null check (applies_to in ('service', 'product')),
  offer_id uuid references bookings.service_offer(id),
  product_id uuid,
  resource_id uuid references bookings.resource(id),
  level text,
  kind text not null check (kind in ('percent', 'fixed')),
  value numeric(18,4) not null check (value >= 0),
  is_active boolean not null default true,
  check ((applies_to = 'service' and product_id is null) or (applies_to = 'product' and offer_id is null)),
  check (kind <> 'percent' or value <= 100)
);
comment on table bookings.commission_rule is 'How much a staff member earns on a service or a product: a percent or a fixed amount.';
alter table bookings.commission_rule enable row level security;
alter table bookings.commission_rule force row level security;
create policy tenant_isolation on bookings.commission_rule
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());


create table bookings.commission_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  checkout_id uuid not null references bookings.checkout(id),
  checkout_line_id uuid references bookings.checkout_line(id),
  resource_id uuid not null references bookings.resource(id),
  user_id uuid,
  applies_to text not null,
  base numeric(18,2) not null,
  kind text not null,
  rate numeric(18,4) not null,
  amount numeric(18,2) not null,
  earned_on date not null,
  reverses_id uuid
);
comment on table bookings.commission_line is 'Commission earned on one checkout line. Never edited: a voided checkout adds a negative line.';
alter table bookings.commission_line enable row level security;
alter table bookings.commission_line force row level security;
create policy tenant_isolation on bookings.commission_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index commission_line_res_ix on bookings.commission_line (company_id, resource_id, earned_on);
create or replace function bookings.refuse_commission_edit() returns trigger language plpgsql as $$
begin
  raise exception 'Commission lines are never changed: add a reversing line instead';
end $$;
create trigger commission_line_immutable before update or delete on bookings.commission_line
  for each row execute function bookings.refuse_commission_edit();

create table bookings.client_fee (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  customer_id uuid not null,
  appointment_id uuid references bookings.appointment(id),
  kind text not null check (kind in ('late_cancel', 'no_show')),
  amount numeric(18,2) not null check (amount > 0),
  status text not null default 'open' check (status in ('open', 'charged', 'waived')),
  waived_reason text,
  checkout_id uuid
);
comment on table bookings.client_fee is 'A late-cancellation or no-show fee waiting to be charged at the client''s next checkout.';
alter table bookings.client_fee enable row level security;
alter table bookings.client_fee force row level security;
create policy tenant_isolation on bookings.client_fee
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create unique index client_fee_appt_ux on bookings.client_fee (appointment_id, kind) where appointment_id is not null;
create index client_fee_open_ix on bookings.client_fee (customer_id) where status = 'open';

create table bookings.recall_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid not null,
  offer_id uuid references bookings.service_offer(id),
  appointment_id uuid references bookings.appointment(id),
  kind text not null default 'recall' check (kind in ('recall', 'rebook')),
  outcome text not null default 'sent' check (outcome in ('sent', 'called', 'booked', 'declined', 'snoozed')),
  snooze_until date,
  note text
);
comment on table bookings.recall_log is 'A reminder that a client is due again, or an invitation to rebook after a visit.';
alter table bookings.recall_log enable row level security;
alter table bookings.recall_log force row level security;
create policy tenant_isolation on bookings.recall_log
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index recall_log_cust_ix on bookings.recall_log (company_id, customer_id, created_at);
create unique index recall_log_appt_ux on bookings.recall_log (appointment_id, kind) where appointment_id is not null;

create table bookings.chair_rental (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  resource_id uuid references bookings.resource(id),
  customer_id uuid not null,
  product_id uuid not null,
  description text not null,
  amount numeric(18,2) not null check (amount > 0),
  every text not null default 'month' check (every in ('week', 'month')),
  start_date date not null,
  next_due date not null,
  end_date date,
  is_active boolean not null default true,
  last_invoice_number text
);
comment on table bookings.chair_rental is 'A chair or room rented to a barber or stylist for a fee every week or month, invoiced by itself.';
alter table bookings.chair_rental enable row level security;
alter table bookings.chair_rental force row level security;
create policy tenant_isolation on bookings.chair_rental
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());


create table bookings.chair_rental_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  rental_id uuid not null references bookings.chair_rental(id),
  period_start date not null,
  invoice_id uuid,
  invoice_number text,
  unique (rental_id, period_start)
);
comment on table bookings.chair_rental_run is 'One invoiced period of a chair rental. Unique per period: a period is invoiced once.';
alter table bookings.chair_rental_run enable row level security;
alter table bookings.chair_rental_run force row level security;
create policy tenant_isolation on bookings.chair_rental_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());


create table bookings.pack_step (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  pack text not null,
  step_id text not null,
  title text not null,
  hint text,
  to_path text,
  check_key text,
  sort_order integer not null default 0,
  done_at timestamptz,
  hidden boolean not null default false,
  unique (company_id, pack, step_id)
);
comment on table bookings.pack_step is 'A first-run step an industry pack gave this business, ticked by itself when the work is done.';
alter table bookings.pack_step enable row level security;
alter table bookings.pack_step force row level security;
create policy tenant_isolation on bookings.pack_step
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());


create table bookings.sample_record (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  entity text not null,
  entity_id uuid not null,
  pack text not null
);
comment on table bookings.sample_record is 'Rows made by the sample-data recipe, so they can be removed together.';
alter table bookings.sample_record enable row level security;
alter table bookings.sample_record force row level security;
create policy tenant_isolation on bookings.sample_record
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create index sample_record_ix on bookings.sample_record (company_id, entity);
