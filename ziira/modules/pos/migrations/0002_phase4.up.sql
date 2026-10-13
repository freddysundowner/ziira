-- Phase 4: devices with codes and numbering, one open till per device and cashier, sales that remember their
-- location, returns that name the sale line, and records that cannot be edited after posting.

alter table pos.pos_device add column code text;
alter table pos.pos_device add column location_id uuid references inventory.location(id);
alter table pos.pos_device add column last_seq bigint not null default 0;
update pos.pos_device set code = 'D' || substr(id::text, 1, 6) where code is null;
alter table pos.pos_device alter column code set not null;
create unique index pos_device_code on pos.pos_device (branch_id, code);

alter table pos.till_session add column local_id uuid;
alter table pos.till_session add column closed_by uuid references kernel.app_user(id);
alter table pos.till_session add column close_note text;
alter table pos.till_session add column report jsonb;
create unique index till_session_local on pos.till_session (tenant_id, local_id) where local_id is not null;
create unique index till_one_open_per_device on pos.till_session (device_id) where status = 'open';
create unique index till_one_open_per_cashier on pos.till_session (cashier_id) where status = 'open';

alter table pos.sale add column location_id uuid references inventory.location(id);
alter table pos.sale add column voided_note text;
create index sale_ix3 on pos.sale (till_session_id);

alter table pos.sales_return add column refund_payment_id uuid references payments.payment(id);
alter table pos.sales_return add column business_date date;
alter table pos.sales_return add column net numeric(18,2);
alter table pos.sales_return add column tax numeric(18,2);
alter table pos.sales_return_line add column sale_line_id uuid references pos.sale_line(id);
create index sales_return_ix1 on pos.sales_return (original_sale_id);

-- A posted sale is a record of what happened: lines and payments never change (a line's cost is filled in once, right
-- after the stock moves), and a sale changes only to be voided.
create function pos.protect_sale_payment() returns trigger language plpgsql as $$
begin
  raise exception 'Sale payments cannot be changed or deleted; void the sale instead' using errcode = '23000';
end $$;
create trigger sale_payment_immutable before update or delete on pos.sale_payment
  for each row execute function pos.protect_sale_payment();

create function pos.protect_sale_line() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' and old.cost_amount is null
     and (new.sale_id, new.line_no, new.product_id, new.quantity, new.unit_price, new.discount_amount,
          new.tax_amount, new.line_total)
         is not distinct from
         (old.sale_id, old.line_no, old.product_id, old.quantity, old.unit_price, old.discount_amount,
          old.tax_amount, old.line_total) then
    return new;
  end if;
  raise exception 'Sale lines cannot be changed or deleted; void the sale instead' using errcode = '23000';
end $$;
create trigger sale_line_immutable before update or delete on pos.sale_line
  for each row execute function pos.protect_sale_line();

create function pos.protect_sale() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Sales cannot be deleted; void the sale instead' using errcode = '23000';
  end if;
  if old.status = 'voided' then
    raise exception 'A voided sale cannot be changed' using errcode = '23000';
  end if;
  if (new.number, new.total, new.tax_total, new.subtotal, new.discount_total, new.business_date, new.branch_id,
      new.company_id, new.local_id, new.cashier_id, new.sold_at)
     is distinct from
     (old.number, old.total, old.tax_total, old.subtotal, old.discount_total, old.business_date, old.branch_id,
      old.company_id, old.local_id, old.cashier_id, old.sold_at) then
    raise exception 'A posted sale cannot be edited; void it and sell again' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger sale_protected before update or delete on pos.sale
  for each row execute function pos.protect_sale();

-- An operation from an offline device that the server could not accept is kept whole, so a sale that really happened
-- is never lost: a manager fixes the cause and the device uploads it again.
create table pos.sync_rejection (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  device_id uuid not null references pos.pos_device(id),
  user_id uuid references kernel.app_user(id),
  local_id uuid not null,
  op_type text not null,
  payload jsonb not null,
  error text not null,
  attempts integer not null default 1,
  resolved_at timestamptz,
  unique (tenant_id, local_id)
);
create index sync_rejection_ix1 on pos.sync_rejection (device_id) where resolved_at is null;
alter table pos.sync_rejection enable row level security;
alter table pos.sync_rejection force row level security;
create policy tenant_isolation on pos.sync_rejection
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
