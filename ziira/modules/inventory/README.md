# Inventory and Branches

**Status:** skeleton. Database tables and manifest are complete; API, services and domain rules are to be built following the `products` module as the template.

| | |
|---|---|
| Schema | `inventory` (see `migrations/0001_init.up.sql`) |
| Requires | products |
| Optional | purchasing, pos |
| Publishes | stock.moved, stock.adjusted, transfer.dispatched, transfer.received, count.posted, stock.below_reorder |
| Subscribes | sale.posted, sale.returned, goods.received |
| Permissions | stock.view, stock.adjust, stock.transfer, stock.count, stock.approve |
| Default roles | Branch Manager: all five · Storekeeper: view, adjust, transfer, count · Cashier, Sales Rep, Accountant: view |
| Reason codes seeded | stock_adjustment, write_off, transfer_variance, count_variance (see `manifest.toml`) |

Next to build (phase 2): see `docs/PROGRESS.md`. Use the kernel services through `ziira.sdk`:
`next_document_number` (ADJ/TRF/CNT numbers), `check_reason`, `submit_for_approval` +
`@subscribe("approval.decided")`, `check_company`, and scope checks with `current_context().require(...)`.

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     one file per use case
domain/       business rules, no database or HTTP
repository/   database access for this schema only
events.py     handlers for subscribed events
public.py     the only file other units may import
```
