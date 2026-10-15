drop table if exists intel.action_log;
drop table if exists intel.auto_rule;
drop table if exists intel.action_proposal;
alter table intel.finding drop column if exists actions_checked_at;
