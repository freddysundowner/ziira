alter table inventory.stock_count_line drop column if exists counted_at;
alter table inventory.stock_count_line drop column if exists counted_seq;
alter table inventory.stock_count drop column if exists snapshot_seq;
drop index if exists inventory.stock_movement_ix3;
drop index if exists inventory.stock_movement_seq;
alter table inventory.stock_movement drop column if exists seq;
