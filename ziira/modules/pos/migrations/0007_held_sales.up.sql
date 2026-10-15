-- Held sales: a cart a cashier parked while the customer fetches something. A draft only: it moves no stock and
-- makes no entry in the books. Resumed, discarded by the cashier, or expired when the till closes.
create table pos.held_sale (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  branch_id uuid not null references kernel.branch(id),
  till_session_id uuid not null references pos.till_session(id),
  cashier_id uuid not null references kernel.app_user(id),
  local_id uuid not null,
  label text not null default '',
  customer_id uuid,
  note text,
  payload jsonb not null,
  status text not null default 'held' check (status in ('held', 'resumed', 'discarded', 'expired')),
  status_at timestamptz,
  unique (tenant_id, local_id)
);
comment on table pos.held_sale is 'Carts parked at a till; drafts that touch neither stock nor the books.';
create index held_sale_ix1 on pos.held_sale (till_session_id) where status = 'held';
alter table pos.held_sale enable row level security;
alter table pos.held_sale force row level security;
create policy tenant_isolation on pos.held_sale
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
