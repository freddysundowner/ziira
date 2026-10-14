-- Tax codes and items carry the codes a tax authority uses, if there is one, under neutral names; a price list's
-- currency is chosen when it is created (the company's base currency), not defaulted.
alter table products.tax_code rename column etims_tax_type to authority_code;
alter table products.tax_code alter column authority_code drop not null;
alter table products.product rename column etims_item_class to authority_item_class;
alter table products.price_list alter column currency drop default;
