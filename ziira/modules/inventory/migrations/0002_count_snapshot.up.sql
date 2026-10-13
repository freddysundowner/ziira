-- Stock counts compare what was counted with what the system held when it was counted, so every movement
-- gets a sequence number: a count remembers the last number at its snapshot, and each counted line the
-- last number when it was counted. Movements between the two are what changed during the count.

alter table inventory.stock_movement add column seq bigint generated always as identity;
create unique index stock_movement_seq on inventory.stock_movement (seq);
create index stock_movement_ix3 on inventory.stock_movement (location_id, product_id, seq);
comment on column inventory.stock_movement.seq is 'Order in which movements were posted (for counts).';

alter table inventory.stock_count add column snapshot_seq bigint not null default 0;
comment on column inventory.stock_count.snapshot_seq is 'Last movement number when the snapshot was taken.';

alter table inventory.stock_count_line add column counted_seq bigint;
alter table inventory.stock_count_line add column counted_at timestamptz;
comment on column inventory.stock_count_line.counted_seq is 'Last movement number when this line was counted.';
