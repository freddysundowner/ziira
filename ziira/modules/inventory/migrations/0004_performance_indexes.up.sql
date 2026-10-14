-- Performance (docs/performance.md): the movement list is shown newest first (all, per location, per product) and
-- checks read recent movements by type. Plain CREATE INDEX (no CONCURRENTLY: migrations run inside a transaction); on
-- a business with millions of movements run this upgrade in a quiet period, it blocks writes while each index builds.
create index if not exists stock_movement_ix4 on inventory.stock_movement (created_at desc, id);
create index if not exists stock_movement_ix5 on inventory.stock_movement (location_id, created_at desc, id);
create index if not exists stock_movement_ix6 on inventory.stock_movement (product_id, created_at desc);
create index if not exists stock_movement_ix7 on inventory.stock_movement (business_date, movement_type);
