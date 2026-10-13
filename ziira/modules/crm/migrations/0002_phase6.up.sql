-- Phase 6: credit changes that wait for approval, lost leads with a reason, and a record of every credit position.

alter table crm.customer_credit_version add column status text not null default 'active'
  check (status in ('pending_approval', 'active', 'superseded', 'rejected'));
alter table crm.customer_credit_version add column previous_limit numeric(18,2);
create unique index customer_one_active_credit on crm.customer_credit_version (customer_id) where status = 'active';
create unique index customer_one_pending_credit on crm.customer_credit_version (customer_id)
  where status = 'pending_approval';

alter table crm.lead add column lost_reason text;
alter table crm.lead add column customer_kind text;
create index lead_ix1 on crm.lead (company_id, status);
create index customer_ix2 on crm.customer (company_id, name);
