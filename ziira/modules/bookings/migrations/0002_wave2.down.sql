-- Ziira Core · schema 'bookings' · undo wave 2
drop table if exists bookings.sample_record, bookings.pack_step, bookings.chair_rental_run, bookings.chair_rental,
  bookings.recall_log, bookings.client_fee, bookings.commission_line, bookings.commission_rule, bookings.checkout_tip,
  bookings.checkout_payment, bookings.checkout_line, bookings.checkout, bookings.session_waitlist,
  bookings.closed_day, bookings.price_variant cascade;
drop function if exists bookings.refuse_commission_edit();
