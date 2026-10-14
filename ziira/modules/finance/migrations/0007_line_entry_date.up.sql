-- Performance (docs/performance.md): every report sums journal lines up to or between dates, which meant joining each
-- line to its entry just to read the entry's date. Lines carry a copy of the date (an entry's date never changes), so a
-- trial balance, profit and loss or balance sheet reads one index.
--
-- A one-time fill of the existing lines lifts the "never changed" guard while it runs; the guard is back before the
-- migration ends. Indexes are created with plain CREATE INDEX (no CONCURRENTLY: migrations run inside a transaction),
-- which blocks writes to journal_line while it builds; run this migration in a quiet period on a large business.

alter table finance.journal_line add column if not exists entry_date date;

alter table finance.journal_line disable trigger journal_line_immutable;
update finance.journal_line l set entry_date = e.entry_date
  from finance.journal_entry e where e.id = l.entry_id and l.entry_date is null;
alter table finance.journal_line enable trigger journal_line_immutable;

alter table finance.journal_line alter column entry_date set not null;
comment on column finance.journal_line.entry_date is 'Copy of the entry''s date (set by the database when a line is added)';

create or replace function finance.set_line_entry_date() returns trigger
  language plpgsql as $$
begin
  if new.entry_date is null then
    select entry_date into new.entry_date from finance.journal_entry where id = new.entry_id;
  end if;
  return new;
end $$;
create trigger journal_line_entry_date before insert on finance.journal_line
  for each row execute function finance.set_line_entry_date();

create index if not exists journal_line_ix4 on finance.journal_line (company_id, entry_date, account_id)
  include (debit, credit, branch_id);
create index if not exists journal_line_ix5 on finance.journal_line (company_id, account_id, entry_date)
  include (debit, credit);
