-- Where a batch came from when no person uploaded a file: another unit staged the rows itself (for example Connectors
-- moving a connected system's data into Ziira). A soft reference: source_kind says what it is, source_id which one.

alter table imports.batch add column source_kind text;
alter table imports.batch add column source_id uuid;
comment on column imports.batch.source_kind is 'What staged the rows when no file was uploaded, e.g. connect.connection';
comment on column imports.batch.source_id is 'The id of that source (a soft reference)';
create index batch_ix2 on imports.batch (tenant_id, source_kind, source_id) where source_id is not null;
