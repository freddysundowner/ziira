-- A service item can say how long it usually takes (a hint: bookings and job estimates may use it as their default).
alter table products.product add column service_minutes integer
  check (service_minutes is null or service_minutes between 1 and 1440);
comment on column products.product.service_minutes is 'Usual duration of a service item, in minutes (null: not said). Only meaningful for product_type service.';
