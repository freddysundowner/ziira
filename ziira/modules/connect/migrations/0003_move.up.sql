-- Connect · moving a connected system's data into Ziira Core, and not checking the same ground twice.
--
-- A move stages the records read from a connection as Data Import batches (one per kind); these tables remember which
-- batches belong to which move, and the Ziira codes given to customers and suppliers so that running the move again
-- gives the same codes (nothing is created twice). `overlap_choice` is the business's answer when both a connected
-- system and Core units cover the same area: keep both checked.

alter table connect.connection add column overlap_choice text check (overlap_choice in ('keep_both'));
alter table connect.connection add column overlap_choice_at timestamptz;
alter table connect.connection add column overlap_choice_by uuid references kernel.app_user(id);
comment on column connect.connection.overlap_choice is 'keep_both: the business chose to keep checking this system while Core covers the same areas';

create table connect.move (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  company_id uuid not null references kernel.company(id),
  as_of date not null,
  options jsonb not null default '{}',
  status text not null default 'running' check (status in ('running', 'done')),
  finished_at timestamptz
);
comment on table connect.move is 'One run of "Move to Ziira Core" for a connection.';
comment on column connect.move.as_of is 'The go-live date: balances and stock are as at this day';
comment on column connect.move.options is 'What was chosen: kinds, default unit and tax code, stock location per branch. No personal data.';
create index move_ix1 on connect.move (tenant_id, connection_id, created_at desc);
alter table connect.move enable row level security;
alter table connect.move force row level security;
create policy tenant_isolation on connect.move
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.move_batch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  move_id uuid not null references connect.move(id) on delete cascade,
  kind text not null,
  phase integer not null check (phase in (1, 2)),
  batch_id uuid,
  staged integer not null default 0,
  note text,
  unique (move_id, kind)
);
comment on table connect.move_batch is 'The Data Import batch a move made for one kind (a soft reference); none when nothing new was found.';
alter table connect.move_batch enable row level security;
alter table connect.move_batch force row level security;
create policy tenant_isolation on connect.move_batch
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table connect.move_code (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  connection_id uuid not null references connect.connection(id) on delete cascade,
  kind text not null check (kind in ('customer', 'supplier')),
  source_ref text not null,
  code text not null,
  matched boolean not null default false,
  created_at timestamptz not null default now(),
  unique (connection_id, kind, source_ref)
);
comment on table connect.move_code is 'The Ziira code of each customer or supplier of a connected system: new, or the existing record it matched.';
alter table connect.move_code enable row level security;
alter table connect.move_code force row level security;
create policy tenant_isolation on connect.move_code
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
