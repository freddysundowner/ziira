-- A business may register to run on Ziira ('core') or only to have Ziira watch the system it already has ('standalone').
alter table master.registration add column mode text not null default 'core' check (mode in ('core', 'standalone'));
