# CRM and Customers

**Status:** skeleton. Database tables and manifest are complete; API, services and domain rules are to be built following the `products` module as the template.

| | |
|---|---|
| Schema | `crm` (see `migrations/0001_init.up.sql`) |
| Requires | kernel only |
| Optional | pos, payments |
| Publishes | lead.created, lead.converted, customer.credit_limit_changed |
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
