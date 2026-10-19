-- Memberships 0002 · undo
drop table if exists memberships.guest_visit;
drop table if exists memberships.checkin;
drop table if exists memberships.freeze;
drop table if exists memberships.plan_price_change;
drop table if exists memberships.dunning_log;
alter table memberships.invoice_run drop column if exists dunning_paused, drop column if exists outstanding,
  drop column if exists settle_state, drop column if exists due_date;
alter table memberships.invoice_run drop constraint if exists invoice_run_owner_type_check;
alter table memberships.invoice_run add constraint invoice_run_owner_type_check
  check (owner_type in ('schedule', 'member', 'package'));
alter table memberships.sold_package drop column if exists billing_customer_id;
alter table memberships.package drop column if exists description, drop column if exists is_example,
  drop column if exists guest;
alter table memberships.member drop column if exists joining_fee_charged, drop column if exists is_trial,
  drop column if exists hold_kind, drop column if exists arrears, drop column if exists past_due_since,
  drop column if exists pending_from, drop column if exists pending_plan_id, drop column if exists price_locked,
  drop column if exists term_end, drop column if exists billing_customer_id;
drop table if exists memberships.waiver_acceptance;
drop table if exists memberships.waiver_version;
drop table if exists memberships.profile;
drop table if exists memberships.account_group;
alter table memberships.setting drop column if exists offline_valid_hours, drop column if exists auto_apply_credit, drop column if exists voucher_product_id,
  drop column if exists referral_reward, drop column if exists point_value, drop column if exists points_per_unit,
  drop column if exists no_show_consumes, drop column if exists late_cancel_consumes,
  drop column if exists late_cancel_hours, drop column if exists expiry_warning_days,
  drop column if exists repeat_window_minutes, drop column if exists waiver_required,
  drop column if exists birthday_messages, drop column if exists inactive_weeks, drop column if exists auto_freeze_days,
  drop column if exists dunning_days, drop column if exists grace_days;
alter table memberships.plan drop column if exists is_example, drop column if exists description,
  drop column if exists guest_passes_per_period, drop column if exists classes_mode, drop column if exists gym_access,
  drop column if exists branch_ids, drop column if exists access_rules, drop column if exists prorate,
  drop column if exists freeze_fee, drop column if exists freeze_max_days, drop column if exists joining_fee_product_id,
  drop column if exists joining_fee, drop column if exists early_exit_fee, drop column if exists notice_days,
  drop column if exists term_periods, drop column if exists is_trial, drop column if exists valid_days,
  drop column if exists kind;
