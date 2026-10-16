alter table command.brief_schedule drop constraint if exists brief_schedule_channel_check;
alter table command.brief_schedule add constraint brief_schedule_channel_check check (channel in ('sms', 'email', 'in_app'));
