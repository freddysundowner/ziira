-- A brief can be scheduled for any channel the business has, so the table no longer lists them ('in_app' stays).
alter table command.brief_schedule drop constraint if exists brief_schedule_channel_check;
alter table command.brief_schedule add constraint brief_schedule_channel_check
  check (channel ~ '^[a-z][a-z0-9_]{1,39}$');
