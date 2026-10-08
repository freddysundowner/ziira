# Inventory and Branches

**Status:** skeleton. Database tables and manifest are complete; API, services and domain rules are to be built following the `products` module as the template.

| | |
|---|---|
| Schema | `inventory` (see `migrations/0001_init.up.sql`) |
| Requires | products |
| Optional | purchasing, pos |
| Publishes | stock.moved, stock.adjusted, transfer.dispatched, transfer.received, count.posted, stock.below_reorder |
| Subscribes | sale.posted, sale.returned, goods.received |

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     one file per use case
domain/       business rules, no database or HTTP
repository/   database access for this schema only
events.py     handlers for subscribed events
public.py     the only file other units may import
```
