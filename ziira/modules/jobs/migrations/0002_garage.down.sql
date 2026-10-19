-- Ziira Core · schema 'jobs' · 0002 down
drop table if exists jobs.loan, jobs.bay_booking, jobs.bay, jobs.job_charge, jobs.part_category, jobs.labour_task,
  jobs.work_type, jobs.job_type;
alter table jobs.estimate_line drop column if exists work_type_code, drop column if exists part_class;
alter table jobs.estimate drop column if exists kind;
alter table jobs.job_part drop column if exists part_class, drop column if exists category_code, drop column if exists source,
  drop column if exists order_status, drop column if exists supplier_id, drop column if exists supplier_name,
  drop column if exists purchase_order_id, drop column if exists purchase_order_number, drop column if exists expected_on,
  drop column if exists ordered_at, drop column if exists arrived_at, drop column if exists cost_price,
  drop column if exists keep_old_part, drop column if exists old_part_note, drop column if exists void_reason;
alter table jobs.job_labour drop column if exists work_type_code, drop column if exists task_code,
  drop column if exists booked_hours, drop column if exists flat_price;
alter table jobs.job_event drop constraint if exists job_event_kind_check;
alter table jobs.job_event add constraint job_event_kind_check check (kind in (
  'received', 'status', 'note', 'assigned', 'estimate', 'approval', 'parts', 'labour', 'invoice', 'collected',
  'rework', 'warranty'));
alter table jobs.job drop column if exists job_type_code, drop column if exists odometer_in, drop column if exists odometer_out,
  drop column if exists fuel_level, drop column if exists key_tag, drop column if exists belongings,
  drop column if exists acknowledged_by_name, drop column if exists acknowledged_at, drop column if exists deposit_amount,
  drop column if exists deposit_payment_id, drop column if exists deposit_at, drop column if exists deposit_note,
  drop column if exists claim_id, drop column if exists storage_fee_waived;
alter table jobs.asset drop column if exists odometer, drop column if exists odometer_at,
  drop column if exists next_service_date, drop column if exists next_service_odometer,
  drop column if exists next_service_note, drop column if exists service_reminded_for;
alter table jobs.setting drop column if exists odometer_unit, drop column if exists unapproved_work,
  drop column if exists release_unpaid, drop column if exists fees_product_id, drop column if exists storage_fee_per_day,
  drop column if exists storage_grace_days, drop column if exists remind_service_due,
  drop column if exists service_reminder_days, drop column if exists ready_reminder_days;
