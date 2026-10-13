drop index if exists crm.customer_ix2;
drop index if exists crm.lead_ix1;
alter table crm.lead drop column if exists customer_kind;
alter table crm.lead drop column if exists lost_reason;
drop index if exists crm.customer_one_pending_credit;
drop index if exists crm.customer_one_active_credit;
alter table crm.customer_credit_version drop column if exists previous_limit;
alter table crm.customer_credit_version drop column if exists status;
