-- Performance (docs/performance.md): bills by status and due date, the lines of a bill or receipt, and the bill lines
-- that bill a receipt line (the three-way match and the purchasing checks). Plain CREATE INDEX (no CONCURRENTLY:
-- migrations run inside a transaction); on a large business run this upgrade in a quiet period.
create index if not exists supplier_bill_ix3 on purchasing.supplier_bill (status, due_date, id);
create index if not exists supplier_bill_ix4 on purchasing.supplier_bill (company_id, bill_date);
create index if not exists supplier_bill_line_ix1 on purchasing.supplier_bill_line (bill_id);
create index if not exists supplier_bill_line_ix2 on purchasing.supplier_bill_line (receipt_line_id);
create index if not exists goods_receipt_line_ix1 on purchasing.goods_receipt_line (receipt_id);
