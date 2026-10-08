-- For a PostgreSQL installed without Docker (Homebrew or Postgres.app).
-- Run as a superuser:  psql -d postgres -f scripts/setup_local_db.sql
create role ziira login password 'ziira' createdb;
create role ziira_app login password 'ziira_app';
create database ziira owner ziira;
