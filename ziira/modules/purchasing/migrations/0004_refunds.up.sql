-- Supplier refunds: when a bill has been paid and then credited (goods sent back after payment), the supplier owes the
-- business money. A refund records the money coming back.

alter table purchasing.supplier_bill add column refunded numeric(18,2) not null default 0;
alter table purchasing.supplier_bill add constraint supplier_bill_refunded_check check (refunded >= 0);

create table purchasing.supplier_refund (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  bill_id uuid not null references purchasing.supplier_bill(id),
  supplier_id uuid not null references purchasing.supplier(id),
  payment_id uuid,
  method text not null,
  amount numeric(18,2) not null check (amount > 0),
  received_on date not null,
  reference text,
  status text not null default 'posted' check (status in ('posted', 'reversed')),
  unique (company_id, number)
);
comment on table purchasing.supplier_refund is 'Money a supplier gave back for goods credited after the bill was paid.';
comment on column purchasing.supplier_refund.payment_id is 'Soft reference to payments.payment';
create index supplier_refund_ix1 on purchasing.supplier_refund (bill_id);
create index supplier_refund_ix2 on purchasing.supplier_refund (payment_id);
alter table purchasing.supplier_refund enable row level security;
alter table purchasing.supplier_refund force row level security;
create policy tenant_isolation on purchasing.supplier_refund
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create function purchasing.protect_refund() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Refunds cannot be deleted; reverse the payment instead' using errcode = '23000';
  end if;
  if (new.number, new.bill_id, new.amount, new.method, new.received_on)
     is distinct from (old.number, old.bill_id, old.amount, old.method, old.received_on) or old.status = 'reversed' then
    raise exception 'A refund cannot be edited; reverse the payment instead' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger supplier_refund_protected before update or delete on purchasing.supplier_refund
  for each row execute function purchasing.protect_refund();
