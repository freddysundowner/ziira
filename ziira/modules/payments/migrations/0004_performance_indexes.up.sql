-- Performance (docs/performance.md): the allocations of a payment, and a payment account's payments by day.
-- Plain CREATE INDEX (no CONCURRENTLY: migrations run inside a transaction); on a large business run this upgrade in a
-- quiet period, it blocks writes while each index builds.
create index if not exists payment_allocation_ix2 on payments.payment_allocation (payment_id);
create index if not exists payment_ix4 on payments.payment (payment_account_id, business_date);
create index if not exists payment_ix5 on payments.payment (branch_id, business_date);
