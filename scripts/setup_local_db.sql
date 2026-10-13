-- For a PostgreSQL installed without Docker (Homebrew or Postgres.app).
-- Run as a superuser:  psql -d postgres -f scripts/setup_local_db.sql
-- ziira owns the master database and creates each tenant's database and login.
create role ziira login password 'ziira' createdb createrole;
create database ziira_master owner ziira;
