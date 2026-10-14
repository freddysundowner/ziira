-- Performance (docs/performance.md): sales listed newest first, a customer's sales, the payments and lines of a sale,
-- a product's sales. Plain CREATE INDEX (no CONCURRENTLY: migrations run inside a transaction); on a large business run
-- this upgrade in a quiet period, it blocks writes while each index builds.
create index if not exists sale_ix4 on pos.sale (sold_at desc, id);
create index if not exists sale_ix5 on pos.sale (branch_id, sold_at desc, id);
create index if not exists sale_ix6 on pos.sale (customer_id, business_date) where customer_id is not null;
create index if not exists sale_payment_ix1 on pos.sale_payment (sale_id);
create index if not exists sale_line_ix1 on pos.sale_line (product_id);
create index if not exists customer_receipt_allocation_ix2 on pos.customer_receipt_allocation (receipt_id);
