-- One-time purchase of a single add-on (a module or plugin) by one business, on top of its plan.
-- The price list reuses master.addon (kind 'unit', is_public = offered for sale) and master.addon_price (interval
-- 'one_time'). What a business bought, or was given by an operator, is a row here; it survives plan changes.

alter table master.billing_invoice drop constraint if exists billing_invoice_kind_check;
alter table master.billing_invoice add constraint billing_invoice_kind_check
  check (kind in ('renewal', 'upgrade', 'manual', 'licence', 'first', 'addon'));

create table master.subscription_addon (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references master.tenant(id) on delete cascade,
  unit_name text not null,
  status text not null default 'pending' check (status in ('pending', 'active', 'revoked', 'void')),
  price numeric(14, 2) not null default 0 check (price >= 0),
  currency char(3) check (currency is null or currency ~ '^[A-Z]{3}$'),
  invoice_id uuid references master.billing_invoice(id),
  payment_reference text,
  idempotency_key text,
  granted_by text not null default 'payment' check (granted_by in ('payment', 'operator')),
  granted_by_name text,
  reason text,
  purchased_at timestamptz,
  revoked_at timestamptz,
  revoked_by text,
  revoke_reason text,
  created_by text,
  created_at timestamptz not null default now(),
  check (granted_by = 'payment' or reason is not null)
);
create unique index subscription_addon_live_ix on master.subscription_addon (tenant_id, unit_name)
  where status in ('pending', 'active');
create unique index subscription_addon_key_ix on master.subscription_addon (tenant_id, idempotency_key)
  where idempotency_key is not null;
create index subscription_addon_invoice_ix on master.subscription_addon (invoice_id);
comment on table master.subscription_addon is 'Add-ons a business bought (one payment) or was given. Pending until its invoice is confirmed paid; active rows add to the plan''s units; revoked/void rows are kept for the record.';
