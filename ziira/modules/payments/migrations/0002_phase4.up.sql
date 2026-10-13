-- Phase 4: provider and callback authentication on payment accounts, phone fingerprints (so matching never needs a
-- stored phone number), STK timing, and uniqueness rules for matches.

alter table payments.payment_account add column provider text not null default 'daraja';
alter table payments.payment_account add column callback_token_hash text;
alter table payments.payment_account add column config jsonb not null default '{}';
create unique index payment_account_callback on payments.payment_account (callback_token_hash)
  where callback_token_hash is not null;
comment on column payments.payment_account.callback_token_hash is 'Hash of the secret in the callback URL Safaricom calls.';
comment on column payments.payment_account.config is 'Non-secret settings: environment (sandbox/production), kind of till.';

alter table payments.external_transaction add column phone_hash text;
comment on column payments.external_transaction.phone_hash is 'Keyed hash of the payer''s phone: matching without storing numbers.';

alter table payments.payment add column phone_hash text;
alter table payments.payment add column till_session_id uuid;
comment on column payments.payment.till_session_id is 'Soft reference to pos.till_session (cash payments).';
create index payment_ix3 on payments.payment (external_ref) where external_ref is not null;

alter table payments.payment_intent add column phone_hash text;
alter table payments.payment_intent add column account_reference text;
alter table payments.payment_intent add column expires_at timestamptz;
alter table payments.payment_intent add column company_id uuid references kernel.company(id);
alter table payments.payment_intent add column branch_id uuid references kernel.branch(id);

create unique index match_one_live on payments.match (external_transaction_id, payment_id) where status <> 'undone';

alter table payments.daily_close add column explanation text;
alter table payments.daily_close add column cash_banked numeric(18,2);
alter table payments.daily_close add column reopened_by uuid references kernel.app_user(id);
