drop index if exists finance.journal_line_ix5;
drop index if exists finance.journal_line_ix4;
drop trigger if exists journal_line_entry_date on finance.journal_line;
drop function if exists finance.set_line_entry_date();
alter table finance.journal_line drop column if exists entry_date;
