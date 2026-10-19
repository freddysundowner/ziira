-- Ziira Core · schema 'jobs' · 0003 down
alter table jobs.setting drop column if exists required_photos;
alter table jobs.job_type drop column if exists required_photos;
drop table if exists jobs.photo_category;
