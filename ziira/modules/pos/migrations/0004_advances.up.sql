-- Advance payments: money a customer paid before (or beyond) what they owed, held on their account until it is applied to
-- an invoice or refunded.

alter table pos.customer_receipt add column unallocated numeric(18,2) not null default 0;
alter table pos.customer_receipt add column refunded numeric(18,2) not null default 0;
alter table pos.customer_receipt add constraint customer_receipt_balances_check
  check (unallocated >= 0 and refunded >= 0 and unallocated + refunded <= amount);

create table pos.customer_refund (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  receipt_id uuid not null references pos.customer_receipt(id),
  customer_id uuid not null,
  payment_id uuid references payments.payment(id),
  till_session_id uuid references pos.till_session(id),
  method text not null,
  amount numeric(18,2) not null check (amount > 0),
  refunded_on date not null,
  reason text not null,
  status text not null default 'posted' check (status in ('posted', 'reversed')),
  unique (company_id, number)
);
comment on table pos.customer_refund is 'Money given back to a customer out of what they had paid in advance.';
create index customer_refund_ix1 on pos.customer_refund (receipt_id);
create index customer_refund_ix2 on pos.customer_refund (payment_id);
alter table pos.customer_refund enable row level security;
alter table pos.customer_refund force row level security;
create policy tenant_isolation on pos.customer_refund
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create function pos.protect_refund() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Refunds cannot be deleted; reverse the payment instead' using errcode = '23000';
  end if;
  if (new.number, new.receipt_id, new.amount, new.method, new.refunded_on, new.customer_id)
     is distinct from (old.number, old.receipt_id, old.amount, old.method, old.refunded_on, old.customer_id)
     or old.status = 'reversed' then
    raise exception 'A refund cannot be edited; reverse the payment instead' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger customer_refund_protected before update or delete on pos.customer_refund
  for each row execute function pos.protect_refund();
