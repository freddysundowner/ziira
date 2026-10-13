# Inventory and Branches

**Status:** working (build plan phase 2). Stock ledger, weighted average costing, locations, opening stock,
adjustments, transfers, counts and the nightly check are built and tested. Not built yet: batch expiry warnings,
landed cost on purchase bills (the receipt event carries it), web screens.

| | |
|---|---|
| Schema | `inventory` (migrations `0001_init`, `0002_count_snapshot`) |
| Requires | products |
| Optional | purchasing, pos |
| Publishes | `stock.moved`, `stock.negative`, `stock.adjusted`, `transfer.dispatched`, `transfer.received`, `count.posted`, `stock.below_reorder` |
| Subscribes | `approval.decided` (kernel), `sale.posted`, `sale.returned`, `goods.received` |
| Plugs into | `kernel.integrity_check` (the stock ledger check) |
| API | `/api/v1/inventory` |
| Permissions | `stock.view`, `stock.adjust`, `stock.transfer`, `stock.count`, `stock.approve`, `stock.cost`, `locations.manage` |
| Default roles | Branch Manager: all · Storekeeper: view, adjust, transfer, count · Finance Manager, Accountant: view + cost · Cashier, Sales Rep: view · Owner: all |
| Reason codes seeded | `stock_adjustment`, `write_off`, `transfer_variance`, `count_variance` |
| Company settings used | `negative_stock_allowed`, `count_variance_threshold` |

## The rules (specification section 08)

- **Stock is a ledger.** Every change is an immutable `stock_movement` (the database rejects UPDATE and DELETE).
  `stock_balance` (per location, product and batch) and `product_cost` (per company and product) are derived and
  updated in the same transaction. `ziira stock-verify` rebuilds them from the movements and reports differences.
- **One place changes stock:** `services/ledger.py: post_movement`. It validates, locks the product's cost row and
  the balance row (always in that order, so postings never deadlock), applies the negative stock policy, costs the
  movement, saves it, updates the figures and publishes events. Nothing else writes to the ledger tables.
- **Weighted average cost** per company: a receipt averages in, anything leaving takes the current average,
  transfers between locations of a company do not change the company's figure (`domain/costing.py`).
- **Negative stock** is a company policy and applies to sales only. If allowed, the sale posts and `stock.negative`
  is published for review; the next receipt corrects the cost through the new average. Offline POS sales are always
  accepted. Every other outgoing movement is blocked when stock is short.
- **Batches:** batch-tracked products name a batch on the way in; going out without a batch picks first expiry,
  first out (`domain/batches.py`).
- **Costs are protected:** movements and product stock show cost and value only to users with `stock.cost`.
- **Scope:** lists and documents are filtered by the branches the user holds `stock.view` for; company-level
  locations (in transit) are visible to anyone with access in the company.

## Endpoints

| Method | Path | Does | Needs |
|---|---|---|---|
| POST, GET | `/locations` | Create / list stores, warehouses, in-transit and virtual locations | `locations.manage` / `stock.view` |
| POST | `/opening-stock` | Opening stock for a location (once per product and location) | `stock.adjust` |
| GET | `/balances`, `/movements`, `/products/{id}/stock` | Read stock and the ledger | `stock.view` (+ `stock.cost` for costs) |
| POST, GET | `/adjustments`, `/adjustments/{id}`; POST `/{id}/submit` | Draft, submit (posts at once or waits for approval) | `stock.adjust` |
| POST, GET | `/transfers`, `/transfers/{id}`; POST `/{id}/dispatch`, `/receive`, `/cancel` | Transfer through in-transit; differences need a reason and may need approval | `stock.transfer` |
| POST, GET | `/counts`, `/counts/{id}`; POST `/{id}/entries`, `/finish`, `/submit`, `/cancel` | Snapshot, count, review, post differences | `stock.count` |

Approvals use the kernel's matrix (`doc_type` `stock_adjustment`, `transfer`, `stock_count`); the approver must hold
the role named in the rule and `stock.approve`. Differences in a count at or below `count_variance_threshold` post
without asking.

## Documents

```
adjustment  draft -> pending_approval -> posted | rejected          (ADJ-<branch>-000001)
transfer    draft -> dispatched -> received | pending_approval      (TRF-...)  dispatch: source -> in transit
count       counting -> review -> posted | pending_approval         (CNT-...)  snapshot at start, each line
                                                                     compared with what the system held when it
                                                                     was counted
```

## Events other units use

Inventory publishes the events above. Other units publish these and Inventory posts the stock
(payloads are documented in `services/stock_events.py`; POS and Purchasing follow them):

| Event | Effect |
|---|---|
| `sale.posted` | `sale` movements, first expiry first out; cost of sales readable with `public.posted_cost` |
| `sale.returned` | `sale_return` at the cost the sale took the stock out at |
| `goods.received` | `receipt` at cost, landed cost spread over the lines, batches created |

## Public interface (`public.py`)

`stock_on_hand(session, product_id, location_id=None, company_id=None)`, `average_cost(session, company_id, product_id)`,
`posted_cost(session, source_type, source_id)`.

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     ledger.py (the one place stock changes), locations, opening_stock, adjustments, transfers,
              counts, stock_events (sale/return/receipt), find_stock, verify
domain/       movements, costing, batches, locations, documents, transfers, counts: no database or HTTP
repository/   models.py and inventory_repo.py
events.py     handlers for subscribed events
hooks.py      the integrity check (kernel.integrity_check)
public.py     the only file other units may import
tests/        domain unit tests and Hypothesis property tests (the API and database tests are in /tests)
```
