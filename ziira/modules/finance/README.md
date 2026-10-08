# Finance and Accounting

**Status:** skeleton. Database tables and manifest are complete; API, services and domain rules are to be built following the `products` module as the template.

| | |
|---|---|
| Schema | `finance` (see `migrations/0001_init.up.sql`) |
| Requires | kernel only |
| Optional | pos, payments, purchasing, inventory, people |
| Publishes | journal.posted, period.closed, expense.approved |
| Subscribes | sale.posted, sale.returned, payment.received, goods.received, bill.posted, stock.adjusted, payroll.approved |

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     one file per use case
domain/       business rules, no database or HTTP
repository/   database access for this schema only
events.py     handlers for subscribed events
public.py     the only file other units may import
```
