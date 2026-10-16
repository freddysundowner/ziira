drop index if exists imports.batch_ix2;
alter table imports.batch drop column source_id;
alter table imports.batch drop column source_kind;
