-- Opening balances: what was found wrong with a whole file (not one row), and undoing a whole import.

alter table imports.batch add column file_check jsonb not null default '{}';
alter table imports.batch add column reverted_at timestamptz;
alter table imports.batch add column reverted_by uuid references kernel.app_user(id);
alter table imports.batch add column revert_reason text;

alter table imports.batch drop constraint batch_status_check;
alter table imports.batch add constraint batch_status_check
  check (status in ('uploaded', 'validated', 'committing', 'done', 'reverted'));
alter table imports.batch_row drop constraint batch_row_status_check;
alter table imports.batch_row add constraint batch_row_status_check
  check (status in ('pending', 'valid', 'invalid', 'imported', 'skipped', 'failed', 'reverted'));
