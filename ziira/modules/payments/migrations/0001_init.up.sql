-- Ziira Core 1.0 · schema 'payments' (Payments and Reconciliation) · install migration
-- Requires: kernel
-- Money in and out, M-Pesa and bank data, matching, daily close.
-- Generated from schema_def.py. Do not edit by hand.


create schema if not exists payments;

create table payments.payment_account (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  kind text not null check (kind in ('cash', 'mpesa_till', 'mpesa_paybill', 'bank', 'card')),
  name text not null,
  shortcode text,
  bank_account_masked text,
  credential_id uuid references kernel.integration_credential(id),
  ledger_account_id uuid,
  is_active boolean not null default true
);
comment on table payments.payment_account is 'A till, Paybill, bank account or cash account.';
comment on column payments.payment_account.shortcode is 'M-Pesa Till or Paybill number';
comment on column payments.payment_account.ledger_account_id is 'Soft reference to finance.account';
alter table payments.payment_account enable row level security;
alter table payments.payment_account force row level security;
create policy tenant_isolation on payments.payment_account
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.external_transaction (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  payment_account_id uuid not null references payments.payment_account(id),
  source text not null check (source in ('daraja_c2b', 'daraja_stk', 'daraja_pull', 'mpesa_statement', 'bank_api', 'bank_statement')),
  external_ref text not null,
  txn_time timestamptz not null,
  direction text not null check (direction in ('in', 'out')),
  amount numeric(18,2) not null check (amount > 0),
  fee numeric(18,2) not null default 0,
  bill_ref text,
  counterparty_name text,
  counterparty_phone_masked text,
  raw jsonb not null,
  match_status text not null default 'unmatched' check (match_status in ('unmatched', 'proposed', 'matched', 'ignored')),
  unique (payment_account_id, external_ref)
);
comment on table payments.external_transaction is 'A raw line from M-Pesa or a bank, normalised.';
comment on column payments.external_transaction.external_ref is 'M-Pesa receipt or bank reference';
comment on column payments.external_transaction.bill_ref is 'Paybill account number entered by payer';
create index external_transaction_ix1 on payments.external_transaction (tenant_id, match_status);
create index external_transaction_ix2 on payments.external_transaction (payment_account_id, txn_time);
alter table payments.external_transaction enable row level security;
alter table payments.external_transaction force row level security;
create policy tenant_isolation on payments.external_transaction
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.payment_intent (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  payment_account_id uuid not null references payments.payment_account(id),
  kind text not null check (kind in ('stk_push', 'b2c')),
  amount numeric(18,2) not null check (amount > 0),
  phone_masked text not null,
  provider_request_id text unique,
  status text not null default 'pending' check (status in ('pending', 'succeeded', 'failed', 'cancelled', 'timeout')),
  result_code text,
  external_transaction_id uuid references payments.external_transaction(id),
  doc_type text,
  doc_id uuid
);
comment on table payments.payment_intent is 'A payment request, e.g. an STK push.';
comment on column payments.payment_intent.provider_request_id is 'e.g. CheckoutRequestID';
alter table payments.payment_intent enable row level security;
alter table payments.payment_intent force row level security;
create policy tenant_isolation on payments.payment_intent
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.payment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  direction text not null check (direction in ('in', 'out')),
  method text not null check (method in ('cash', 'mpesa', 'bank', 'card', 'cheque', 'other')),
  payment_account_id uuid not null references payments.payment_account(id),
  amount numeric(18,2) not null check (amount > 0),
  business_date date not null,
  party_type text check (party_type in ('customer', 'supplier', 'employee', 'other')),
  party_id uuid,
  external_ref text,
  status text not null default 'posted' check (status in ('draft', 'posted', 'reversed')),
  unique (company_id, number)
);
comment on table payments.payment is 'Money received or paid, linked to a party.';
comment on column payments.payment.party_id is 'Soft reference to the party''s module';
create index payment_ix1 on payments.payment (tenant_id, business_date);
create index payment_ix2 on payments.payment (party_type, party_id);
alter table payments.payment enable row level security;
alter table payments.payment force row level security;
create policy tenant_isolation on payments.payment
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.payment_allocation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  payment_id uuid not null references payments.payment(id),
  doc_type text not null,
  doc_id uuid not null,
  amount numeric(18,2) not null check (amount > 0)
);
comment on table payments.payment_allocation is 'What a payment pays for.';
comment on column payments.payment_allocation.doc_type is 'sale, invoice, supplier_bill, payslip';
create index payment_allocation_ix1 on payments.payment_allocation (doc_type, doc_id);
alter table payments.payment_allocation enable row level security;
alter table payments.payment_allocation force row level security;
create policy tenant_isolation on payments.payment_allocation
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.match (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  external_transaction_id uuid not null references payments.external_transaction(id),
  payment_id uuid not null references payments.payment(id),
  amount numeric(18,2) not null,
  stage text not null check (stage in ('exact_reference', 'account_number', 'rule', 'manual')),
  rule_code text,
  confidence numeric(5,4),
  status text not null default 'applied' check (status in ('proposed', 'applied', 'undone')),
  undone_by uuid references kernel.app_user(id),
  undone_at timestamptz
);
comment on table payments.match is 'Link between an external transaction and a payment.';
alter table payments.match enable row level security;
alter table payments.match force row level security;
create policy tenant_isolation on payments.match
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.daily_close (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  business_date date not null,
  status text not null default 'open' check (status in ('open', 'submitted', 'locked', 'reopened')),
  totals jsonb not null default '{}',
  variance numeric(18,2) not null default 0,
  submitted_by uuid references kernel.app_user(id),
  submitted_at timestamptz,
  locked_at timestamptz,
  unique (branch_id, business_date)
);
comment on table payments.daily_close is 'Branch close for a business date.';
comment on column payments.daily_close.totals is 'Expected and actual per method';
alter table payments.daily_close enable row level security;
alter table payments.daily_close force row level security;
create policy tenant_isolation on payments.daily_close
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table payments.recon_exception (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  branch_id uuid references kernel.branch(id),
  kind text not null,
  ref_type text not null,
  ref_id uuid not null,
  amount numeric(18,2),
  status text not null default 'open' check (status in ('open', 'explained', 'resolved', 'dismissed')),
  assigned_to uuid references kernel.app_user(id),
  resolution_note text,
  resolved_by uuid references kernel.app_user(id),
  resolved_at timestamptz
);
comment on table payments.recon_exception is 'An item needing review.';
comment on column payments.recon_exception.kind is 'unmatched_receipt, unpaid_sale, close_variance, duplicate_ref, ...';
create index recon_exception_ix1 on payments.recon_exception (tenant_id, status);
alter table payments.recon_exception enable row level security;
alter table payments.recon_exception force row level security;
create policy tenant_isolation on payments.recon_exception
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

