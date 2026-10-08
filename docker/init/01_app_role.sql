-- The application connects as ziira_app, which does not own the tables,
-- so row-level security applies to every query it runs.
create role ziira_app login password 'ziira_app';
