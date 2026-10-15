drop table if exists intel.ai_ranking;
drop table if exists intel.ask_message;
drop table if exists intel.ask_session;
drop table if exists intel.ai_call_log;
drop table if exists intel.ai_usage;
drop table if exists intel.ai_consent;
alter table intel.finding drop column if exists explanation_ai_tried_at, drop column if exists explanation_ai_at,
  drop column if exists explanation_ai;
