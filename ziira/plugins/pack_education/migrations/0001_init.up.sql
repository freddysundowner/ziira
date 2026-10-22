-- An industry pack keeps no tables: the units copy its data files into their own.
create schema if not exists plg_pack_education;
comment on schema plg_pack_education is 'Pack Education (industry pack)';
