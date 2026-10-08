# Point of Sale and Sales

**Status:** skeleton. Database tables and manifest are complete; API, services and domain rules are to be built following the `products` module as the template.

| | |
|---|---|
| Schema | `pos` (see `migrations/0001_init.up.sql`) |
| Requires | products, inventory, payments |
| Optional | crm, finance |
| Publishes | sale.posted, sale.voided, sale.returned, discount.override, till.opened, till.closed, invoice.issued |
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
