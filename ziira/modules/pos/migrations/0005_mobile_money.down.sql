alter table pos.customer_refund disable trigger user;
update pos.customer_refund set method = 'mpesa' where method = 'mobile_money';
alter table pos.customer_refund enable trigger user;
alter table pos.customer_receipt disable trigger user;
update pos.customer_receipt set method = 'mpesa' where method = 'mobile_money';
alter table pos.customer_receipt enable trigger user;
alter table pos.sales_return drop constraint sales_return_refund_method_check;
update pos.sales_return set refund_method = 'mpesa' where refund_method = 'mobile_money';
alter table pos.sales_return add constraint sales_return_refund_method_check
  check (refund_method in ('cash', 'mpesa', 'credit_note', 'exchange'));
alter table pos.sale_payment drop constraint sale_payment_method_check;
alter table pos.sale_payment disable trigger user;
update pos.sale_payment set method = 'mpesa' where method = 'mobile_money';
alter table pos.sale_payment enable trigger user;
alter table pos.sale_payment add constraint sale_payment_method_check
  check (method in ('cash', 'mpesa', 'card', 'credit', 'other'));
