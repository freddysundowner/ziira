-- Performance (docs/performance.md): the lines of a payslip. Plain CREATE INDEX (migrations run inside a transaction).
create index if not exists payslip_line_ix1 on people.payslip_line (payslip_id);
