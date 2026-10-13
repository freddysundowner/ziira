# Point of Sale and Sales

**Status:** working for phase 4: devices, till sessions with X and Z reports, sales at the till, voids, returns with
refunds and approval, price overrides, and offline sync. Not built yet: quotations, sales orders and invoices (the tables
exist), credit sales and credit notes (phase 6 with customer accounts), receipts printing, eTIMS (phase 5).

| | |
|---|---|
| Schema | `pos` (migrations `0001_init`, `0002_phase4`) |
| Requires | products, inventory, payments |
| Optional | crm, finance |
| Publishes | `sale.posted`, `sale.voided`, `sale.returned`, `discount.override`, `till.opened`, `till.closed`, `pos.synced` |
| Subscribes | `approval.decided` (kernel): posts or rejects a return that waited for approval |
| API | `/api/v1/pos` |
| Permissions | `sales.sell`, `sales.void`, `sales.refund`, `price.override`, `till.manage` (own till), `till.review` (any till at a branch), `devices.manage`, `invoices.manage` (later) |
| Default roles | Cashier: sell, own till · Branch Manager: everything · Finance Manager and Accountant: review tills |
| Reason lists | `void`, `sale_return`, `price_override`, `till_variance` (seeded, editable) |

## How a sale works

A sale is one transaction: the sale and its lines, its payments (recorded through Payments, allocated to the sale and
tied to the till session), the stock leaving (Inventory reacts to `sale.posted` in the same transaction) and the books
(Finance does the same). If any part refuses, the whole sale is refused and nothing is half done.

- **Prices include VAT.** A line is `quantity x unit price - discount`; the VAT inside it is `gross x rate / (100 + rate)`,
  rounded half up. Prices come from the branch's default price list, then the company's (Products: `price-lists`).
- **Overrides.** Any price other than the list price, any discount, and any product with no list price needs
  `price.override` and a reason from the `price_override` list; `discount.override` is published for Intelligence.
- **Payments.** cash, mpesa, card, other. Only cash can be more than is due (the rest is change and is not takings). An
  M-Pesa payment needs its code; the same code for the same amount cannot be used twice.
- **Numbers.** Online: `POS-<branch>-<device>-000123`, gap-free per device. Offline sales carry the device's own number
  `POS-<branch>-<device>-L000123`, so the two never collide.
- **Retries.** A `local_id` (or an `Idempotency-Key`) makes a sale happen once however often it is sent.
- **Immutable.** Sale lines and payments cannot be changed (the database refuses); a sale changes only to be voided.
- **Void** (while the till is open): payments reversed, stock back at the cost it left with, books reversed. After the till
  is closed, take the goods back as a **return**: refunded from what each line really sold for (parts add up exactly),
  restocked, and put through the `sales_return` approval rule if there is one.

## Tills

`open` (float) -> sales -> `close` (cash counted). Expected cash is the float plus cash taken less cash refunded; any
difference needs a reason from `till_variance`, is posted to the books by Finance (`till.closed`) and is put in front of a
manager. A cashier has one open till and a device has one. A branch cannot close its day while a till is open.

## Offline

A device holds a key (shown once at registration; send it as `X-Device-Key` together with the cashier's sign-in).

1. `GET /sync/snapshot` pages through products, prices and stock to keep on the device.
2. Offline, the device records `till_open`, `sale` and `till_close` operations, each with an id it made.
3. `POST /sync/upload` sends them in order. It is safe to send again: an operation already accepted is answered
   (`duplicate`), not redone, whether the batch is repeated, cut off halfway or sent twice at once.

A sale made offline has already happened, so it is **accepted whenever it is well formed**, and what does not add up goes to
the exceptions inbox: a price that changed since the snapshot, stock that was not there, a discount without permission or
reason, an M-Pesa payment without its code, a day closed in the meantime (booked today), a till closed by a manager.
An operation that cannot be accepted at all is kept whole in `pos.sync_rejection` (`GET /sync/rejections`) and flagged;
fix the cause and the device sends it again.

## Layout

```
api/          routes.py, schemas.py
services/     devices, tills, sales (sell and void), returns, catalog, sync, access
domain/       sales.py: line money, change, refunds in parts, numbering (pure, unit-tested)
repository/   models.py, pos_repo.py
events.py     approval.decided -> returns
public.py     open_till_sessions (used by the daily close)
tests/        domain tests; flows are in the top-level tests/ (test_pos_*.py)
```
