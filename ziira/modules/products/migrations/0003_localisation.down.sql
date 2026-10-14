alter table products.price_list alter column currency set default 'KES';
alter table products.product rename column authority_item_class to etims_item_class;
update products.tax_code set authority_code = 'B' where authority_code is null;
alter table products.tax_code alter column authority_code set not null;
alter table products.tax_code rename column authority_code to etims_tax_type;
