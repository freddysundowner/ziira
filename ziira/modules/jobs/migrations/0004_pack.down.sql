-- Ziira Core · schema 'jobs' · 0004 down
drop table if exists jobs.sample_item, jobs.sample_recipe, jobs.pack_step;
alter table jobs.setting drop column if exists pack_name;
