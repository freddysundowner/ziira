-- An industry pack keeps no tables: it supplies data files that the units copy into the business's own tables.
create schema if not exists plg_pack_demo_services;
comment on schema plg_pack_demo_services is 'Demo services (industry pack)';
