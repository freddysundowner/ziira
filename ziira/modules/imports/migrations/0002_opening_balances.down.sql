update imports.batch_row set status = 'imported' where status = 'reverted';
update imports.batch set status = 'done' where status = 'reverted';
alter table imports.batch_row drop constraint batch_row_status_check;
alter table imports.batch_row add constraint batch_row_status_check
  check (status in ('pending', 'valid', 'invalid', 'imported', 'skipped', 'failed'));
alter table imports.batch drop constraint batch_status_check;
alter table imports.batch add constraint batch_status_check
  check (status in ('uploaded', 'validated', 'committing', 'done'));
alter table imports.batch drop column revert_reason;
alter table imports.batch drop column reverted_by;
alter table imports.batch drop column reverted_at;
alter table imports.batch drop column file_check;
