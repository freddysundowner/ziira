-- Opening balances: what the business owed a supplier when it moved onto Ziira. An *opening bill* is a posted bill with no
-- lines, no goods, no tax and nothing to match, carrying the supplier's invoice number and the original dates so payables
-- ageing is right. It is paid like any bill.

alter table purchasing.supplier_bill add column kind text not null default 'bill'
  check (kind in ('bill', 'opening_balance'));
comment on column purchasing.supplier_bill.kind is 'bill: an ordinary supplier bill; opening_balance: brought in at go-live';
