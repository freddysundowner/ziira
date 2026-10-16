-- Self-service subscription payments: which payment gateways the platform owner has switched on (settings and
-- encrypted secrets), and every attempt a business makes to pay an invoice through one. Which gateways exist is
-- decided by plugins; nothing here names a provider, a currency or a country.

create table master.payment_gateway (
  name text primary key,
  enabled boolean not null default false,
  config jsonb not null default '{}',
  secrets_encrypted text,
  default_for text[] not null default '{}',
  updated_at timestamptz not null default now(),
  updated_by text
);
comment on table master.payment_gateway is 'The platform owner''s settings for each payment gateway plugin. secrets_encrypted is a Fernet token of a JSON object (API keys, webhook secrets): write-only, never returned, logged or audited with values. default_for lists currency or country codes this gateway is preferred for.';

create table master.payment_attempt (
  id uuid primary key default gen_random_uuid(),
  reference text not null unique,
  invoice_id uuid not null references master.billing_invoice(id),
  tenant_id uuid not null references master.tenant(id),
  provider text not null,
  amount numeric(14, 2) not null check (amount > 0),
  currency char(3) not null,
  status text not null default 'initiated'
    check (status in ('initiated', 'pending', 'completed', 'failed', 'expired', 'mismatch')),
  payer_phone_last4 text,
  payer_phone_hash text,
  payer_email text,
  provider_transaction_id text,
  checkout_request_id text,
  redirect_url text,
  payment_reference text,
  result_code text,
  result_desc text,
  created_by text,
  completed_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  last_checked_at timestamptz
);
create index payment_attempt_invoice_ix on master.payment_attempt (invoice_id, created_at);
create index payment_attempt_tenant_ix on master.payment_attempt (tenant_id, created_at);
create index payment_attempt_open_ix on master.payment_attempt (status, created_at) where status in ('initiated', 'pending');
create index payment_attempt_txn_ix on master.payment_attempt (provider, provider_transaction_id);
-- One open attempt per invoice: a second click can never start a second charge.
create unique index payment_attempt_one_open_ix on master.payment_attempt (invoice_id) where status in ('initiated', 'pending');
comment on table master.payment_attempt is 'One try to pay an invoice through a gateway. The payer''s phone number is never stored whole: only its last four digits and a keyed hash (to match a data request).';

create table master.payment_attempt_event (
  id bigint generated always as identity primary key,
  attempt_id uuid not null references master.payment_attempt(id),
  occurred_at timestamptz not null default now(),
  kind text not null,
  event_key text,
  detail jsonb
);
create index payment_attempt_event_ix on master.payment_attempt_event (attempt_id, id);
-- A provider notification already handled is not handled twice.
create unique index payment_attempt_event_key_ix on master.payment_attempt_event (attempt_id, event_key) where event_key is not null;
comment on table master.payment_attempt_event is 'The timeline of an attempt: started, checked, notified, credited, flagged. Append-only.';
create or replace function master.forbid_payment_event_change() returns trigger language plpgsql as $$
begin
  raise exception 'The payment attempt timeline cannot be changed' using errcode = '23000';
end $$;
create trigger payment_attempt_event_immutable before update or delete on master.payment_attempt_event
  for each row execute function master.forbid_payment_event_change();
