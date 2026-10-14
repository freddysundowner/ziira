drop table if exists intel.check_setting;
drop index if exists intel.baseline_ix2;
alter table intel.baseline drop column if exists company_id;
drop index if exists intel.finding_event_ix1;
drop index if exists intel.finding_ix3;
drop index if exists intel.finding_ux_fingerprint;
alter table intel.finding drop column if exists area, drop column if exists alerted_at, drop column if exists amount,
  drop column if exists recommended_action, drop column if exists summary, drop column if exists fingerprint,
  drop column if exists check_code;
alter table intel.check_definition drop column if exists description, drop column if exists area;
