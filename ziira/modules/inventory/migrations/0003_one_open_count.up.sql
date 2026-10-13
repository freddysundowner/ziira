-- At most one count in progress per location (the service checks too; this makes it impossible to break).
create unique index stock_count_one_open on inventory.stock_count (location_id)
  where status in ('counting', 'review', 'pending_approval');
