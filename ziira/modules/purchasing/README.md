# Purchasing and Suppliers

**Status:** skeleton. Database tables and manifest are complete; API, services and domain rules are to be built following the `products` module as the template.

| | |
|---|---|
| Schema | `purchasing` (see `migrations/0001_init.up.sql`) |
| Requires | products |
| Optional | inventory, finance |
| Publishes | po.approved, goods.received, bill.posted, bill.match_exception, supplier.bank_changed, supplier.price_changed |
| Subscribes | none |

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     one file per use case
domain/       business rules, no database or HTTP
repository/   database access for this schema only
events.py     handlers for subscribed events
public.py     the only file other units may import
```
