update purchasing.supplier_bill set kind = 'bill' where kind = 'opening_balance';
alter table purchasing.supplier_bill drop column kind;
