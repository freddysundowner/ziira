-- A supplier's tax number, and the reference a tax authority gave a supplier's invoice, without any country's name.
alter table purchasing.supplier rename column kra_pin to tax_id;
alter table purchasing.supplier_bill rename column etims_ref to authority_ref;
