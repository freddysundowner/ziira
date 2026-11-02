-- Ziira Core · schema 'jobs' · 0005 down
drop table if exists jobs.job_inspection_item;
drop table if exists jobs.job_timer;
alter table jobs.job drop column if exists appointment_id, drop column if exists storage_invoice_number,
  drop column if exists storage_invoice_id, drop column if exists deposit_applied;
