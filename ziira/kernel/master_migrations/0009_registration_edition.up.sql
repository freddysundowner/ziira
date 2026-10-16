-- A registration asks for an edition (a bundle of units: retail, distribution, books, intelligence, full).
-- `mode` stays for older callers: 'standalone' is the intelligence edition, 'core' anything else.
alter table master.registration add column edition text not null default 'full';
update master.registration set edition = 'intelligence' where mode = 'standalone';
