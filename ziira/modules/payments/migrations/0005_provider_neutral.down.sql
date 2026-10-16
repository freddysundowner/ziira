alter table payments.payment_account alter column provider set default 'daraja';
alter table payments.external_transaction drop constraint external_transaction_source_check;
alter table payments.external_transaction add constraint external_transaction_source_check
  check (source in ('daraja_c2b', 'daraja_stk', 'daraja_pull', 'mpesa_statement', 'bank_api', 'bank_statement'));
