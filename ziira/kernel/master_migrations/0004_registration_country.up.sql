alter table master.registration add column country char(2) check (country is null or country ~ '^[A-Z]{2}$');
