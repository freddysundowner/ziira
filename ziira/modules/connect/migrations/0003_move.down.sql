drop table if exists connect.move_code;
drop table if exists connect.move_batch;
drop table if exists connect.move;
alter table connect.connection drop column if exists overlap_choice_by;
alter table connect.connection drop column if exists overlap_choice_at;
alter table connect.connection drop column if exists overlap_choice;
