drop table if exists command.brief;
drop table if exists command.pulse_figure;
alter table command.brief_schedule drop constraint if exists brief_schedule_channel_check;
alter table command.brief_schedule add constraint brief_schedule_channel_check
  check (channel in ('whatsapp', 'email', 'in_app'));
alter table command.brief_schedule alter column channel set default 'whatsapp';
