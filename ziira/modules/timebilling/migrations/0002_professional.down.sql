drop table if exists timebilling.sample_item;
drop table if exists timebilling.sample_recipe;
drop table if exists timebilling.snippet;
drop table if exists timebilling.activity;
drop table if exists timebilling.engagement_template;
alter table timebilling.rate drop column if exists example;
drop table if exists timebilling.nudge_log;
drop table if exists timebilling.engagement_task;
drop table if exists timebilling.recurrence;
alter table timebilling.invoice_batch_line drop column if exists automatic, drop column if exists write_down_reason,
  drop column if exists list_minutes, drop column if exists list_amount;
alter table timebilling.invoice_batch drop column if exists narrative, drop column if exists review_note,
  drop column if exists review_at, drop column if exists review_by, drop column if exists review_requested_at,
  drop column if exists review_requested_by, drop column if exists review_status;
alter table timebilling.retainer drop column if exists auto_draft, drop column if exists bill_day;
alter table timebilling.entry drop column if exists written_off;
alter table timebilling.expense drop column if exists written_off, drop column if exists category;
alter table timebilling.client_terms drop column if exists expense_markup_percent;
alter table timebilling.staff drop column if exists nudges, drop column if exists away_until, drop column if exists approver_id;
alter table timebilling.setting drop column if exists approval_escalate_days, drop column if exists approval_reminder_days,
  drop column if exists work_days, drop column if exists nudge_hour, drop column if exists nudge_minutes,
  drop column if exists receipt_required_above, drop column if exists default_markup_percent,
  drop column if exists partner_review_above, drop column if exists partner_review;
update timebilling.project set billing_mode = 'time_and_materials' where billing_mode = 'capped_fee';
alter table timebilling.project drop column if exists fee_cap;
alter table timebilling.project drop constraint if exists project_billing_mode_check;
alter table timebilling.project add constraint project_billing_mode_check
  check (billing_mode in ('time_and_materials', 'fixed_fee', 'retainer'));
