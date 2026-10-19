-- Memberships 0003 · undo
drop table if exists memberships.trainer_earning;
drop table if exists memberships.trainer_rate;
drop table if exists memberships.measurement;
drop table if exists memberships.locker;
drop table if exists memberships.value_entry;
drop table if exists memberships.value_account;
alter table memberships.invoice_run drop column if exists for_label, drop column if exists for_customer_id;
alter table memberships.schedule drop column if exists for_label, drop column if exists for_customer_id;
