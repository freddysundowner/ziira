# Point of Sale and Sales

**Status:** working for phases 4 and 6: devices, tills with X and Z reports, sales, voids, returns, price overrides and
offline sync (phase 4); and, with CRM, **credit sales, invoices, quotations and sales orders, customer payments, credit
notes, advance payments, statements, ageing and reminders sent by SMS or email** (phase 6), and **printable receipts, invoices and payment receipts** (text for thermal printers, HTML, or data).

| | |
|---|---|
| Schema | `pos` (migrations `0001_init`, `0002_phase4`) |
| Requires | products, inventory, payments |
| Optional | crm (customers, credit), finance |
| Publishes | `sale.posted`, `sale.voided`, `sale.returned`, `discount.override`, `till.opened`, `till.closed`, `pos.synced`, `invoice.issued`, `invoice.cancelled`, `customer.paid`, `customer.payment_reversed`, `customer.over_limit_attempt` |
| Subscribes | `approval.decided` (kernel): a return or a sales order that waited for approval · `payment.reversed` (Payments): the invoices a reversed customer payment paid are owed again, a refund goes back on account |
| API | `/api/v1/pos` |
| Permissions | `sales.sell`, `sales.void`, `sales.refund`, `price.override`, `till.manage` (own till), `till.review` (any till at a branch), `devices.manage`, `invoices.manage`, `receivables.view`, `receivables.manage` |
| Default roles | Cashier: sell, own till, take customer payments · Branch Manager: everything · Finance Manager: invoices, receivables, tills · Accountant: receivables, tills · Sales Rep: sell, invoices, receivables view |
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

## Customers on account (phase 6)

- **Credit sales.** A till sale can leave all or part of its total on the customer's account (`payments: [{method:
  credit}]`, with the customer named). The customer must be active and the sale must keep them within their credit limit
  and terms (CRM); credit decisions for one customer are taken one at a time, so two sales cannot both fit under the same
  limit. The sale makes an **invoice** for the part on credit; Finance debits accounts receivable (against the customer)
  instead of cash. Offline, a credit sale that already happened is accepted and an over-limit or on-hold customer is raised
  to a manager (`customer.over_limit_attempt`).
- **Invoices to business customers.** `POST /invoices`, or deliver a **sales order**: quotation -> order (approved by amount
  if a rule exists) -> delivery, which is an invoice for the quantities on it at the prices agreed (each delivery takes stock
  out). The customer's group price list applies; changing a price needs `price.override` and a reason. Invoices are never
  edited: cancel (nothing paid, credited or returned) and issue again.
- **Advance payments.** A payment may be more than is owed if the payer says to *hold the balance* (`hold_balance`): what is
  left stays on the customer's account, which is then in credit (negative `owes`, `credit_on_account`). It is applied to
  invoices later (`POST /customers/{id}/apply-credit`: no money moves, no entry is made) or given back
  (`POST /receipts/{id}/refund`: cash out of the till, M-Pesa or bank; reversible). Credit on account counts against what
  the customer owes when their limit is checked. A payment that has been partly refunded cannot be reversed until the
  refund is.
- **Customers paying.** `POST /receipts` shares a payment over the customer's invoices (the oldest first, or those named),
  never more than is owed; it is recorded through Payments (so M-Pesa and bank money match as usual) and cash can go
  through the cashier's till. Reversing it (here or in Payments) makes the invoices owed again.
- **Credit notes.** Goods taken back from a credit sale or an invoice are refunded as a *credit note* (less owed) while the
  invoice is unpaid, and in cash or M-Pesa once it is paid. Voiding a credit sale cancels its invoice.
- **Statements and ageing.** `GET /customers/{id}/statement` (invoices, credit notes and payments with a running balance),
  `/receivables/ageing` (by due date), `/receivables/reminders` (who to chase) and `POST /invoices/{id}/reminders` to record
  a chase. A cashier can see a customer's balance but not browse debtors.
- **Reminders are sent.** `POST /invoices/{id}/send-reminder` and `POST /receivables/send-reminders` message the customer
  (SMS or email; their phone or email from CRM) through the kernel's messaging and note the reminder; one a day per
  invoice and channel, nothing to someone on the do-not-contact list. With the company setting `reminder_channel` turned on,
  a daily recurring task (`pos.send_reminders`) chases invoices `reminder_min_days_overdue` days late, no more often than
  every `reminder_repeat_days`. Old quotations are expired by another recurring task.
- **Printing.** `GET /sales/{id}/receipt`, `/invoices/{id}/print` and `/receipts/{id}/print` return the document as data
  (`format=json`, default), as text for a thermal printer (`format=text`, `width` 32, 40 or 48) or as HTML for A4
  (`format=html`); `copy=true` marks a reprint. The header is the company and branch, with a VAT breakdown by rate and
  footers from the company settings `receipt_footer` and `invoice_footer`. User text is escaped in HTML. Other units add
  lines to the foot through the extension point `pos.receipt_extras` (contract `ReceiptExtra` in `public.py`); a plugin
  that fails there never stops a document being printed.
- **Checked every night** (`ziira verify`, "customer ledger"): what the invoices say each customer owes equals what the books
  say, and every invoice's paid amount equals its live receipts.

## Layout

```
api/          routes.py, schemas.py
services/     devices, tills, sales (sell and void), returns (sales and invoices), catalog, sync, access;
              credit, invoices, documents (quotations and orders), customer_receipts, receivables
domain/       sales.py: line money, change, refunds in parts, numbering (pure, unit-tested)
repository/   models.py, pos_repo.py
events.py     approval.decided -> returns
public.py     open_till_sessions (used by the daily close), customer_balance
hooks.py      the customer ledger check
tests/        domain tests; flows are in the top-level tests/ (test_pos_*.py)
```
