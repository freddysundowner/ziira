-- Phase 6: invoices (for credit sales and for business customers), receipts from customers, quotations and orders that
-- deliver stock, and returns against invoices.

alter table pos.sales_invoice add column kind text not null default 'invoice' check (kind in ('invoice', 'credit_sale'));
alter table pos.sales_invoice add column location_id uuid references inventory.location(id);
alter table pos.sales_invoice add column credited numeric(18,2) not null default 0;
alter table pos.sales_invoice add column cancelled_at timestamptz;
alter table pos.sales_invoice add column cancelled_by uuid references kernel.app_user(id);
alter table pos.sales_invoice add column cancel_reason text;
alter table pos.sales_invoice add column notes text;
create unique index sales_invoice_one_per_sale on pos.sales_invoice (sale_id) where sale_id is not null;
create index sales_invoice_ix3 on pos.sales_invoice (company_id, status, due_date);

alter table pos.sales_invoice_line add column line_no smallint;
alter table pos.sales_invoice_line add column batch_id uuid references inventory.batch(id);
alter table pos.sales_invoice_line add column cost_amount numeric(18,2);
alter table pos.sales_invoice_line add column order_line_id uuid references pos.sales_document_line(id);
alter table pos.sales_invoice_line add column price_reason_code_id uuid references kernel.reason_code(id);
alter table pos.sales_invoice_line add column list_price numeric(18,2);

alter table pos.sales_document add column location_id uuid references inventory.location(id);
alter table pos.sales_document add column terms_days integer not null default 0;
alter table pos.sales_document add column notes text;
alter table pos.sales_document add column subtotal numeric(18,2) not null default 0;
alter table pos.sales_document add column tax_total numeric(18,2) not null default 0;
alter table pos.sales_document_line add column line_no smallint;
alter table pos.sales_document_line add column tax_amount numeric(18,2) not null default 0;
create index sales_document_ix1 on pos.sales_document (company_id, doc_kind, status);

alter table pos.sales_return_line add column invoice_line_id uuid references pos.sales_invoice_line(id);

-- A receipt is a customer's payment, shared out over the invoices it paid.
create table pos.customer_receipt (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  customer_id uuid not null,
  payment_id uuid references payments.payment(id),
  till_session_id uuid references pos.till_session(id),
  method text not null,
  amount numeric(18,2) not null check (amount > 0),
  received_on date not null,
  reference text,
  status text not null default 'posted' check (status in ('posted', 'reversed')),
  reversed_at timestamptz,
  reverse_reason text,
  unique (company_id, number)
);
comment on table pos.customer_receipt is 'A payment from a customer against their invoices.';
comment on column pos.customer_receipt.customer_id is 'Soft reference to crm.customer';
create index customer_receipt_ix1 on pos.customer_receipt (customer_id, received_on);
create index customer_receipt_ix2 on pos.customer_receipt (payment_id);
alter table pos.customer_receipt enable row level security;
alter table pos.customer_receipt force row level security;
create policy tenant_isolation on pos.customer_receipt
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table pos.customer_receipt_allocation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  receipt_id uuid not null references pos.customer_receipt(id),
  invoice_id uuid not null references pos.sales_invoice(id),
  amount numeric(18,2) not null check (amount > 0)
);
create index customer_receipt_allocation_ix1 on pos.customer_receipt_allocation (invoice_id);
alter table pos.customer_receipt_allocation enable row level security;
alter table pos.customer_receipt_allocation force row level security;
create policy tenant_isolation on pos.customer_receipt_allocation
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create trigger customer_receipt_allocation_immutable before update or delete on pos.customer_receipt_allocation
  for each row execute function kernel.forbid_change();
create function pos.protect_receipt() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Receipts cannot be deleted; reverse the payment instead' using errcode = '23000';
  end if;
  if (new.number, new.customer_id, new.amount, new.method, new.received_on, new.company_id)
     is distinct from (old.number, old.customer_id, old.amount, old.method, old.received_on, old.company_id)
     or (old.status = 'reversed') then
    raise exception 'A receipt cannot be edited; reverse the payment instead' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger customer_receipt_protected before update or delete on pos.customer_receipt
  for each row execute function pos.protect_receipt();

-- Invoices: lines never change (a line's cost is filled in once, after the stock moves); the invoice itself changes
-- only in what has been paid or credited, and in being cancelled.
create function pos.protect_invoice_line() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' and old.cost_amount is null
     and (new.invoice_id, new.product_id, new.quantity, new.unit_price, new.discount_amount, new.tax_amount,
          new.line_total) is not distinct from
         (old.invoice_id, old.product_id, old.quantity, old.unit_price, old.discount_amount, old.tax_amount,
          old.line_total) then
    return new;
  end if;
  raise exception 'Invoice lines cannot be changed or deleted; cancel the invoice instead' using errcode = '23000';
end $$;
create trigger sales_invoice_line_immutable before update or delete on pos.sales_invoice_line
  for each row execute function pos.protect_invoice_line();

create function pos.protect_invoice() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Invoices cannot be deleted; cancel the invoice instead' using errcode = '23000';
  end if;
  if old.status = 'cancelled' then
    raise exception 'A cancelled invoice cannot be changed' using errcode = '23000';
  end if;
  if (new.number, new.customer_id, new.total, new.subtotal, new.tax_total, new.issue_date, new.due_date,
      new.company_id, new.sale_id, new.kind)
     is distinct from
     (old.number, old.customer_id, old.total, old.subtotal, old.tax_total, old.issue_date, old.due_date,
      old.company_id, old.sale_id, old.kind) then
    raise exception 'An issued invoice cannot be edited; cancel it and issue a new one' using errcode = '23000';
  end if;
  if new.amount_paid < 0 or new.credited < 0 or new.amount_paid + new.credited > new.total then
    raise exception 'An invoice cannot be paid or credited for more than it is worth' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger sales_invoice_protected before update or delete on pos.sales_invoice
  for each row execute function pos.protect_invoice();

-- A record of the reminders sent about overdue invoices (sending itself arrives with notifications).
create table pos.invoice_reminder (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  invoice_id uuid not null references pos.sales_invoice(id),
  channel text not null check (channel in ('whatsapp', 'sms', 'email', 'call', 'visit')),
  note text
);
create index invoice_reminder_ix1 on pos.invoice_reminder (invoice_id, created_at);
alter table pos.invoice_reminder enable row level security;
alter table pos.invoice_reminder force row level security;
create policy tenant_isolation on pos.invoice_reminder
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger invoice_reminder_immutable before update or delete on pos.invoice_reminder
  for each row execute function kernel.forbid_change();
