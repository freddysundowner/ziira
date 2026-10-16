drop table if exists intel.suppression_rule;
drop index if exists intel.finding_ix_snoozed;
alter table intel.finding drop column if exists snoozed_until;
