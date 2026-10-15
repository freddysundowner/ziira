-- Opening balances: the books of a business that moves onto Ziira start from one "opening balance entry" per company,
-- dated the go-live date. This table is the document behind that entry (the entry itself is an ordinary immutable
-- journal entry). A second one needs the first to be reversed.

create table finance.opening_balance (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  number text not null,
  go_live_date date not null,
  entry_id uuid not null references finance.journal_entry(id),
  line_count integer not null check (line_count > 0),
  difference numeric(18,2) not null default 0,
  note text,
  status text not null default 'posted' check (status in ('posted', 'reversed')),
  reversal_entry_id uuid references finance.journal_entry(id),
  reversed_at timestamptz,
  reversed_by uuid references kernel.app_user(id),
  reverse_reason text,
  unique (company_id, number)
);
comment on table finance.opening_balance is 'The opening balance entry of a company: its balance-sheet accounts at the go-live date.';
comment on column finance.opening_balance.difference is
  'What the file was out by (debits less credits) and was posted to opening balance equity because the user confirmed it';
create unique index opening_balance_one_live on finance.opening_balance (company_id) where status = 'posted';
alter table finance.opening_balance enable row level security;
alter table finance.opening_balance force row level security;
create policy tenant_isolation on finance.opening_balance
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- Never edited or deleted; the only change allowed is to be reversed, once.
create function finance.protect_opening_balance() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'An opening balance entry cannot be deleted; reverse it instead' using errcode = '23000';
  end if;
  if old.status = 'reversed'
     or (new.number, new.company_id, new.go_live_date, new.entry_id, new.line_count, new.difference)
        is distinct from (old.number, old.company_id, old.go_live_date, old.entry_id, old.line_count, old.difference) then
    raise exception 'An opening balance entry cannot be edited; reverse it instead' using errcode = '23000';
  end if;
  return new;
end $$;
create trigger opening_balance_protected before update or delete on finance.opening_balance
  for each row execute function finance.protect_opening_balance();
