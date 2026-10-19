-- Ziira Core · schema 'claims' (Third-party payer claims) · install migration
-- Requires: kernel only. Customers (crm), jobs, appointments and invoices (pos) are plain ids: those units are optional.
-- A claim is "someone else pays": an insurer, a fleet owner, a medical scheme, an employer. Estimates go to the payer in
-- numbered versions; the payer answers each line; the answers are kept for ever (append-only); the money is invoiced in
-- runs through the Point of Sale invoice service and paid through its receipts.

create schema if not exists claims;

create table claims.setting (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id) unique,
  invoice_product_id uuid,
  unapproved_work text not null default 'warn' check (unapproved_work in ('warn', 'block')),
  estimate_valid_days integer not null default 14 check (estimate_valid_days between 1 and 365),
  link_valid_days integer not null default 14 check (link_valid_days between 1 and 90),
  short_pay_tolerance numeric(18,2) not null default 0 check (short_pay_tolerance >= 0)
);
comment on table claims.setting is 'Per-company claim settings. Claim invoices are made under one service item, whose tax code decides the tax.';
alter table claims.setting enable row level security;
alter table claims.setting force row level security;
create policy tenant_isolation on claims.setting
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table claims.payer (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  customer_id uuid,
  name text not null,
  kind text not null default 'insurer' check (kind in ('insurer', 'scheme', 'fleet', 'employer', 'other')),
  labour_rates jsonb not null default '{}',
  parts_discount_pct numeric(7,4) not null default 0 check (parts_discount_pct between 0 and 100),
  parts_markup_pct numeric(7,4) not null default 0 check (parts_markup_pct between 0 and 1000),
  paint_rate numeric(18,2) check (paint_rate is null or paint_rate >= 0),
  approval_limit numeric(18,2) check (approval_limit is null or approval_limit >= 0),
  payment_days integer not null default 30 check (payment_days between 0 and 365),
  required_documents jsonb not null default '[]',
  contacts jsonb not null default '[]',
  estimate_email text,
  notes text,
  is_active boolean not null default true,
  unique (company_id, name)
);
comment on table claims.payer is 'Someone who pays on the customer''s behalf, with their terms as data (rates per work type, parts rules, approval limit, payment days).';
alter table claims.payer enable row level security;
alter table claims.payer force row level security;
create policy tenant_isolation on claims.payer
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index payer_ix1 on claims.payer (company_id, customer_id);

create table claims.claim (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  number text not null,
  payer_id uuid not null references claims.payer(id),
  customer_id uuid,
  insured_name text,
  insured_phone text,
  source_type text check (source_type in ('job', 'appointment')),
  source_id uuid,
  source_number text,
  subject text,
  policy_number text,
  claim_number text,
  member_number text,
  preauth_ref text,
  loss_date date,
  loss_description text,
  assessor_name text,
  assessor_phone text,
  excess_amount numeric(18,2) not null default 0 check (excess_amount >= 0),
  status text not null default 'draft' check (status in ('draft', 'open', 'authorised', 'completed', 'invoiced', 'settled', 'closed')),
  closed_reason text check (closed_reason in ('total_loss', 'salvage', 'cash_in_lieu', 'rejected', 'withdrawn', 'cancelled', 'written_off')),
  closed_note text,
  closed_amount numeric(18,2),
  closed_at timestamptz,
  authority_ref text,
  authority_amount numeric(18,2),
  authority_by text,
  authority_at timestamptz,
  completed_at timestamptz,
  completion_signed_by text,
  completion_signed_at timestamptz,
  completion_note text,
  invoiced_at timestamptz,
  unique (company_id, number),
  check ((source_type is null) = (source_id is null)),
  check ((status = 'closed') = (closed_reason is not null))
);
comment on table claims.claim is 'One claim per job or appointment where a payer is involved.';
alter table claims.claim enable row level security;
alter table claims.claim force row level security;
create policy tenant_isolation on claims.claim
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index claim_ix1 on claims.claim (company_id, status);
create index claim_ix2 on claims.claim (payer_id, status);
create index claim_ix3 on claims.claim (source_type, source_id);
create unique index claim_live_source on claims.claim (company_id, source_type, source_id)
  where source_id is not null and status <> 'closed';

create table claims.estimate (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  seq integer not null check (seq > 0),
  lineage_id uuid not null,
  lineage_kind text not null check (lineage_kind in ('original', 'supplementary')),
  lineage_no integer not null default 0 check (lineage_no >= 0),
  version integer not null default 1 check (version > 0),
  previous_id uuid references claims.estimate(id),
  status text not null default 'draft' check (status in ('draft', 'submitted', 'answered', 'superseded', 'withdrawn')),
  title text,
  notes text,
  revision_note text,
  valid_until date,
  total numeric(18,2) not null default 0,
  submitted_at timestamptz,
  submitted_by uuid references kernel.app_user(id),
  submitted_via text,
  answered_at timestamptz,
  response text check (response in ('accepted', 'partly_accepted', 'countered', 'rejected', 'needs_information', 'withdrawn')),
  unique (claim_id, seq)
);
comment on table claims.estimate is 'A numbered version of the estimate sent to the payer. A supplementary estimate is its own lineage.';
alter table claims.estimate enable row level security;
alter table claims.estimate force row level security;
create policy tenant_isolation on claims.estimate
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index estimate_ix1 on claims.estimate (claim_id, lineage_id, version);
create index estimate_ix2 on claims.estimate (company_id, status);

create table claims.estimate_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  estimate_id uuid not null references claims.estimate(id),
  position integer not null,
  kind text not null check (kind in ('labour', 'parts', 'paint', 'sundries', 'other')),
  work_type text,
  part_class text check (part_class in ('genuine', 'aftermarket', 'used')),
  description text not null,
  quantity numeric(18,4) not null check (quantity > 0),
  unit_price numeric(18,4) not null check (unit_price >= 0),
  asked_total numeric(18,2) not null check (asked_total >= 0),
  product_id uuid,
  carried_from_id uuid references claims.estimate_line(id),
  locked boolean not null default false,
  payer_state text not null default 'pending' check (payer_state in ('pending', 'approved', 'countered', 'rejected', 'needs_information')),
  payer_amount numeric(18,2) check (payer_amount is null or payer_amount >= 0),
  payer_reason text,
  responded_at timestamptz,
  our_decision text check (our_decision in ('accepted', 'declined')),
  customer_decision text check (customer_decision in ('pays', 'declined')),
  customer_decision_by text,
  customer_decision_at timestamptz,
  shortfall_to text check (shortfall_to in ('customer', 'business')),
  invoiced_run_id uuid
);
comment on table claims.estimate_line is 'A line of an estimate with the payer''s current answer. Every answer ever given is in claims.line_response.';
alter table claims.estimate_line enable row level security;
alter table claims.estimate_line force row level security;
create policy tenant_isolation on claims.estimate_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index estimate_line_ix1 on claims.estimate_line (estimate_id, position);
create index estimate_line_ix2 on claims.estimate_line (claim_id);

create table claims.line_response (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  estimate_id uuid not null references claims.estimate(id),
  line_id uuid not null references claims.estimate_line(id),
  round integer not null check (round > 0),
  state text not null check (state in ('approved', 'countered', 'rejected', 'needs_information', 'reduced')),
  amount numeric(18,2),
  reason text,
  by_name text,
  by_user uuid references kernel.app_user(id),
  channel text not null check (channel in ('link', 'staff')),
  via text,
  answered_at timestamptz not null default now()
);
comment on table claims.line_response is 'Append-only: every answer the payer gave on a line, in every round.';
alter table claims.line_response enable row level security;
alter table claims.line_response force row level security;
create policy tenant_isolation on claims.line_response
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index line_response_ix1 on claims.line_response (line_id, created_at);
create index line_response_ix2 on claims.line_response (estimate_id, round);
create trigger line_response_immutable before update or delete on claims.line_response
  for each row execute function kernel.forbid_change();

create table claims.estimate_response (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  estimate_id uuid not null references claims.estimate(id),
  round integer not null check (round > 0),
  response text not null check (response in ('accepted', 'partly_accepted', 'countered', 'rejected', 'needs_information', 'withdrawn')),
  by_name text not null,
  by_user uuid references kernel.app_user(id),
  channel text not null check (channel in ('link', 'staff')),
  via text,
  occurred_at timestamptz not null,
  note text,
  authority_ref text,
  authority_amount numeric(18,2),
  unique (estimate_id, round)
);
comment on table claims.estimate_response is 'Append-only: each answer of the payer to an estimate (who, when, how).';
alter table claims.estimate_response enable row level security;
alter table claims.estimate_response force row level security;
create policy tenant_isolation on claims.estimate_response
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create trigger estimate_response_immutable before update or delete on claims.estimate_response
  for each row execute function kernel.forbid_change();

create table claims.claim_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  estimate_id uuid references claims.estimate(id),
  kind text not null check (kind in ('created', 'estimate', 'submitted', 'response', 'decision', 'authority', 'note', 'assessor_visit', 'reinspection', 'completion', 'invoice', 'credit', 'payment', 'short_pay', 'closed', 'link', 'work', 'information')),
  note text,
  occurred_on date,
  actor_name text,
  actor_id uuid references kernel.app_user(id),
  channel text
);
comment on table claims.claim_event is 'The timeline of a claim.';
alter table claims.claim_event enable row level security;
alter table claims.claim_event force row level security;
create policy tenant_isolation on claims.claim_event
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index claim_event_ix1 on claims.claim_event (claim_id, created_at);
create trigger claim_event_immutable before update or delete on claims.claim_event
  for each row execute function kernel.forbid_change();

create table claims.estimate_link (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  estimate_id uuid not null references claims.estimate(id),
  token_hash text not null unique,
  expires_at timestamptz not null,
  sent_via text,
  sent_to text,
  revoked_at timestamptz,
  revoked_by uuid references kernel.app_user(id),
  signed_off_at timestamptz,
  signer_name text,
  view_count integer not null default 0,
  last_accessed_at timestamptz
);
comment on table claims.estimate_link is 'A secure response link for one estimate: only a hash of the secret is stored; expires; can be revoked.';
alter table claims.estimate_link enable row level security;
alter table claims.estimate_link force row level security;
create policy tenant_isolation on claims.estimate_link
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index estimate_link_ix1 on claims.estimate_link (estimate_id);

create table claims.link_access (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  link_id uuid not null references claims.estimate_link(id),
  action text not null,
  outcome text not null,
  ip_address text,
  user_agent text
);
comment on table claims.link_access is 'Append-only: every time a response link was opened, answered or refused.';
alter table claims.link_access enable row level security;
alter table claims.link_access force row level security;
create policy tenant_isolation on claims.link_access
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index link_access_ix1 on claims.link_access (link_id, created_at);
create trigger link_access_immutable before update or delete on claims.link_access
  for each row execute function kernel.forbid_change();

create table claims.work_decision (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  estimate_id uuid references claims.estimate(id),
  decided_by uuid references kernel.app_user(id),
  note text not null
);
comment on table claims.work_decision is 'A recorded decision to go ahead with work the payer has not approved (yet).';
alter table claims.work_decision enable row level security;
alter table claims.work_decision force row level security;
create policy tenant_isolation on claims.work_decision
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index work_decision_ix1 on claims.work_decision (claim_id);

create table claims.invoice_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  seq integer not null check (seq > 0),
  payer_invoice_id uuid,
  payer_invoice_number text,
  payer_amount numeric(18,2) not null default 0,
  excess_applied numeric(18,2) not null default 0,
  customer_invoice_id uuid,
  customer_invoice_number text,
  customer_amount numeric(18,2) not null default 0,
  unique (claim_id, seq)
);
comment on table claims.invoice_run is 'One billing of a claim: a payer invoice and a customer invoice (a supplementary estimate approved later is a later run).';
alter table claims.invoice_run enable row level security;
alter table claims.invoice_run force row level security;
create policy tenant_isolation on claims.invoice_run
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());


create table claims.invoice_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  run_id uuid not null references claims.invoice_run(id),
  side text not null check (side in ('payer', 'customer')),
  kind text not null check (kind in ('line', 'excess', 'shortfall', 'rejected_line', 'recharge')),
  estimate_line_id uuid references claims.estimate_line(id),
  invoice_line_id uuid,
  amount numeric(18,2) not null,
  discount numeric(18,2) not null default 0 check (discount >= 0),
  credited_at timestamptz,
  credit_number text
);
comment on table claims.invoice_line is 'Which claim line went on which invoice line (so a payer reduction can credit exactly that line).';
alter table claims.invoice_line enable row level security;
alter table claims.invoice_line force row level security;
create policy tenant_isolation on claims.invoice_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index invoice_line_ix1 on claims.invoice_line (run_id);
create index invoice_line_ix2 on claims.invoice_line (estimate_line_id);

create table claims.payer_receipt (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  payer_id uuid not null references claims.payer(id),
  pos_receipt_id uuid,
  pos_receipt_number text,
  amount numeric(18,2) not null check (amount > 0),
  method text not null,
  reference text,
  received_on date not null,
  note text,
  unique (company_id, payer_id, reference)
);
comment on table claims.payer_receipt is 'Money received from a payer (remittance), recorded through the Point of Sale receipt service.';
alter table claims.payer_receipt enable row level security;
alter table claims.payer_receipt force row level security;
create policy tenant_isolation on claims.payer_receipt
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());


create table claims.payer_receipt_allocation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  receipt_id uuid not null references claims.payer_receipt(id),
  run_id uuid not null references claims.invoice_run(id),
  claim_id uuid not null references claims.claim(id),
  invoice_id uuid not null,
  amount numeric(18,2) not null check (amount > 0),
  closes_invoice boolean not null default false
);
alter table claims.payer_receipt_allocation enable row level security;
alter table claims.payer_receipt_allocation force row level security;
create policy tenant_isolation on claims.payer_receipt_allocation
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index payer_receipt_allocation_ix1 on claims.payer_receipt_allocation (run_id);

create table claims.short_pay (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  claim_id uuid not null references claims.claim(id),
  payer_id uuid not null references claims.payer(id),
  run_id uuid not null references claims.invoice_run(id),
  invoice_id uuid not null,
  expected numeric(18,2) not null,
  paid numeric(18,2) not null,
  difference numeric(18,2) not null check (difference > 0),
  status text not null default 'open' check (status in ('open', 'disputed', 'recharged', 'accepted')),
  note text,
  resolved_at timestamptz,
  resolved_by uuid references kernel.app_user(id),
  recharge_invoice_number text
);
comment on table claims.short_pay is 'The payer paid less than the invoice and called it settled: the difference, and what was decided.';
alter table claims.short_pay enable row level security;
alter table claims.short_pay force row level security;
create policy tenant_isolation on claims.short_pay
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create index short_pay_ix1 on claims.short_pay (company_id, status);
create unique index short_pay_one_open on claims.short_pay (invoice_id) where status in ('open', 'disputed');
