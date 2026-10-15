drop trigger if exists opening_balance_protected on finance.opening_balance;
drop function if exists finance.protect_opening_balance();
drop table if exists finance.opening_balance;
