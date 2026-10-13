-- Reversing a posted bill, returning goods to a supplier, supplier credit notes, and landed-cost lines on a bill.

alter table purchasing.supplier_bill drop constraint supplier_bill_status_check;
alter table purchasing.supplier_bill add constraint supplier_bill_status_check
  check (status in ('draft', 'pending_approval', 'posted', 'part_paid', 'paid', 'cancelled', 'reversed'));
alter table purchasing.supplier_bill add column credited numeric(18,2) not null default 0;
alter table purchasing.supplier_bill add column reversed_at timestamptz;
alter table purchasing.supplier_bill add column reversed_by uuid references kernel.app_user(id);
alter table purchasing.supplier_bill add column reverse_reason text;
alter table purchasing.supplier_bill add column posted_figures jsonb;
drop index purchasing.supplier_bill_one_per_invoice;
create unique index supplier_bill_one_per_invoice on purchasing.supplier_bill (supplier_id, supplier_invoice_no)
  where status not in ('cancelled', 'reversed');
alter table purchasing.supplier_bill_line add column landed_receipt_id uuid references purchasing.goods_receipt(id);

create table purchasing.purchase_return (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  supplier_id uuid not null references purchasing.supplier(id),
  receipt_id uuid not null references purchasing.goods_receipt(id),
  location_id uuid not null,
  reason_code_id uuid not null references kernel.reason_code(id),
  note text,
  returned_at timestamptz not null,
  unique (company_id, number)
);
comment on table purchasing.purchase_return is 'Goods sent back to a supplier.';
create index purchase_return_ix1 on purchasing.purchase_return (receipt_id);
alter table purchasing.purchase_return enable row level security;
alter table purchasing.purchase_return force row level security;
create policy tenant_isolation on purchasing.purchase_return
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.purchase_return_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  return_id uuid not null references purchasing.purchase_return(id),
  receipt_line_id uuid not null references purchasing.goods_receipt_line(id),
  product_id uuid not null references products.product(id),
  quantity numeric(18,4) not null check (quantity > 0),
  unit_cost numeric(18,6) not null,
  stock_value numeric(18,2) not null default 0,
  qty_credited numeric(18,4) not null default 0
);
comment on column purchasing.purchase_return_line.stock_value is 'What the stock that left was worth (at average cost)';
comment on column purchasing.purchase_return_line.qty_credited is 'Quantity covered by supplier credit notes';
create index purchase_return_line_ix1 on purchasing.purchase_return_line (receipt_line_id);
alter table purchasing.purchase_return_line enable row level security;
alter table purchasing.purchase_return_line force row level security;
create policy tenant_isolation on purchasing.purchase_return_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.supplier_credit_note (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid references kernel.branch(id),
  number text not null,
  supplier_id uuid not null references purchasing.supplier(id),
  bill_id uuid not null references purchasing.supplier_bill(id),
  supplier_credit_no text not null,
  credit_date date not null,
  subtotal numeric(18,2) not null,
  tax_total numeric(18,2) not null,
  total numeric(18,2) not null check (total > 0),
  unique (company_id, number),
  unique (supplier_id, supplier_credit_no)
);
comment on table purchasing.supplier_credit_note is 'A credit the supplier gave against one of its bills.';
alter table purchasing.supplier_credit_note enable row level security;
alter table purchasing.supplier_credit_note force row level security;
create policy tenant_isolation on purchasing.supplier_credit_note
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table purchasing.supplier_credit_note_line (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  credit_note_id uuid not null references purchasing.supplier_credit_note(id),
  return_line_id uuid references purchasing.purchase_return_line(id),
  expense_account_id uuid,
  description text,
  quantity numeric(18,4) not null check (quantity > 0),
  unit_cost numeric(18,6) not null,
  tax_code_id uuid references products.tax_code(id),
  tax_amount numeric(18,2) not null default 0,
  line_total numeric(18,2) not null
);
alter table purchasing.supplier_credit_note_line enable row level security;
alter table purchasing.supplier_credit_note_line force row level security;
create policy tenant_isolation on purchasing.supplier_credit_note_line
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- Returns, credit notes and their lines are records of what happened: never edited or deleted. (The credited quantity
-- of a return line is the one thing that moves, and only upwards.)
create trigger supplier_credit_note_immutable before update or delete on purchasing.supplier_credit_note
  for each row execute function kernel.forbid_change();
create trigger supplier_credit_note_line_immutable before update or delete on purchasing.supplier_credit_note_line
  for each row execute function kernel.forbid_change();
create trigger purchase_return_immutable before update or delete on purchasing.purchase_return
  for each row execute function kernel.forbid_change();
create function purchasing.protect_return_line() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' and (new.return_id, new.receipt_line_id, new.product_id, new.quantity, new.unit_cost)
       is not distinct from (old.return_id, old.receipt_line_id, old.product_id, old.quantity, old.unit_cost)
     and new.qty_credited >= old.qty_credited and new.qty_credited <= new.quantity
     and (old.stock_value = 0 or new.stock_value = old.stock_value) then
    return new;
  end if;
  raise exception 'A returned line cannot be changed or deleted' using errcode = '23000';
end $$;
create trigger purchase_return_line_protected before update or delete on purchasing.purchase_return_line
  for each row execute function purchasing.protect_return_line();
