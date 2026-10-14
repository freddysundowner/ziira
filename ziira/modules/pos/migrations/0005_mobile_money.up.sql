-- The payment method "mpesa" is now "mobile_money": which service provides it is the payment account's business. This is a
-- relabel of the method code on existing rows (no amount, date or document changes), so the protection triggers are
-- paused for it.

alter table pos.sale_payment drop constraint sale_payment_method_check;
alter table pos.sale_payment disable trigger user;
update pos.sale_payment set method = 'mobile_money' where method = 'mpesa';
alter table pos.sale_payment enable trigger user;
alter table pos.sale_payment add constraint sale_payment_method_check
  check (method in ('cash', 'mobile_money', 'card', 'credit', 'other'));

alter table pos.sales_return drop constraint sales_return_refund_method_check;
update pos.sales_return set refund_method = 'mobile_money' where refund_method = 'mpesa';
alter table pos.sales_return add constraint sales_return_refund_method_check
  check (refund_method in ('cash', 'mobile_money', 'credit_note', 'exchange'));

alter table pos.customer_receipt disable trigger user;
update pos.customer_receipt set method = 'mobile_money' where method = 'mpesa';
alter table pos.customer_receipt enable trigger user;

alter table pos.customer_refund disable trigger user;
update pos.customer_refund set method = 'mobile_money' where method = 'mpesa';
alter table pos.customer_refund enable trigger user;
