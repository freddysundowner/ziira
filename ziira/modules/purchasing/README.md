# Purchasing and Suppliers

**Status:** working for phase 7: suppliers (with guarded bank details), purchase requests and orders, goods receipts,
supplier bills with the three-way match, payment of bills, returns to suppliers, supplier credit notes, reversal of bills
and of payments, landed-cost invoices, and what is owed to suppliers by age. Not built yet: pulling supplier invoices
from eTIMS (the eTIMS plugin), reconciling a supplier's statement, supplier refunds of overpaid bills.

| | |
|---|---|
| Schema | `purchasing` (migrations `0001_init`, `0002_phase7`) |
| Requires | products |
| Optional | inventory (receiving goods), finance (expense accounts and the books), payments (paying bills) |
| Publishes | `po.approved`, `goods.received`, `goods.returned`, `bill.posted`, `bill.reversed`, `bill.match_exception`, `credit_note.posted`, `supplier.bank_changed`, `supplier.price_changed`, `supplier.paid`, `supplier.payment_reversed` |
| Subscribes | `approval.decided` (kernel): purchase requests, orders, bills and supplier bank changes · `payment.reversed` (Payments): a bill whose payment was reversed is owed again |
| API | `/api/v1/purchasing` |
| Permissions | `suppliers.manage`, `supplier.bank_edit`, `supplier.bank_confirm`, `po.create`, `po.approve`, `goods.receive`, `goods.return`, `bills.manage`, `bills.approve`, `bills.pay`, `purchasing.view` |
| Default roles | Finance Manager: all · Branch Manager: view, order, receive · Storekeeper: view, receive · Accountant: view, suppliers, bills |
| Company setting | `bill_match_tolerance_percent` (default 2) |
| Reason lists | `bill_exception`, `purchase_return` |

## The flow

```
request (draft -> approved -> ordered)
order   draft -> (approval by amount, document type purchase_order) -> approved -> sent -> part_received -> received
receipt against the order (partial is fine, never more than ordered) -> stock arrives (Inventory) -> booked against
        "goods received not invoiced" (Finance)
bill    draft -> submit -> three-way match -> posted -> part_paid -> paid
```

- **Costs are before VAT**; VAT is added at each line's tax code (selling prices include it, costs do not).
- **Receiving** is one transaction with the stock arriving. Against an order the cost comes from the order; the difference
  with the supplier's invoice shows up on the bill. `landed_cost` is spread over the lines by value (Inventory).
- **Three-way match** (on submit): quantity billed cannot exceed what was received and not yet billed; cost per unit must be
  within `bill_match_tolerance_percent` of the order (or receipt). A bill that matches posts (or waits for an approver if its
  amount needs one: document type `supplier_bill`). One that does not is an **exception**: raised in the exceptions inbox
  and it posts only when someone *else* with `bills.approve` accepts it, with a reason from `bill_exception`.
- **Posting a bill** publishes `bill.posted`; Finance debits goods received not invoiced at what was received, books any
  price difference to *purchase price variance*, VAT input, expense accounts for non-goods lines, and credits accounts
  payable. **Paying** goes through Payments and publishes `supplier.paid` (debit payable, credit cash/bank/M-Pesa).
- **Supplier bank details** change only in three steps: one person proposes (`supplier.bank_edit`), a *different* person
  confirms with the supplier directly (`supplier.bank_confirm`; phone call-back, in person or signed letter), then the
  approval matrix (document type `supplier_bank_change`). The number is stored encrypted and only the last four digits are
  ever shown; earlier details are kept as history.
- **Records are guarded:** receipt lines and supplier prices cannot be changed or deleted, bills and receipts cannot be
  deleted, and a bill's lines cannot change once it is submitted.

## Putting things right

- **Reversing a payment** (`POST /bills/{id}/reverse-payment`, or directly in Payments): the bill is owed again and Finance
  puts the money back (`supplier.payment_reversed`).
- **Reversing a bill** (`POST /bills/{id}/reverse`, `bills.approve`, with a reason): Finance books the mirror image, what was
  billed on the orders goes back, and the supplier's invoice number can be entered again. Not while the bill has payments
  or credit notes: reverse the payments first.
- **Sending goods back** (`POST /receipts/{id}/returns`, `goods.return`, reason from `purchase_return`): the stock leaves at
  the average cost it is held at (`goods.returned`), the order's received quantity goes down so a replacement can be received
  on the same order, and goods not yet billed cannot be billed. If they were already billed the return is flagged in the
  exceptions inbox until the supplier's credit note is entered.
- **Supplier credit notes** (`POST /bills/{id}/credit-notes`, `bills.approve`): reduce what is owed on a posted bill (never by
  more than is still owed). Credit for returned goods clears "goods received not invoiced" at the stock's value and puts
  any difference with the credit given to *purchase price variance*; other credits name the expense account they reduce.
- **Landed cost** (transport, duty): a bill line with `landed_receipt_id` (quantity 1) clears the landed part of that
  receipt's "goods received not invoiced"; billing more than the receipt recorded is a match exception. The charge usually
  comes from a different supplier than the goods.
- Because outgoing stock is always costed at the average, a returned item can differ slightly from the cost it arrived at;
  the credit note books that difference to purchase price variance.

## Layout

```
api/          routes.py, schemas.py
services/     suppliers (+ bank details), orders (+ requests), receipts, returns, bills (+ payment, reversal, payables),
              credit_notes, access, common
domain/       rules.py: costs and VAT, the match, order status, ageing, validation (pure, unit-tested)
repository/   models.py, purchasing_repo.py
events.py     approval.decided
public.py     supplier_balance
tests/        domain tests; flows are in the top-level tests/ (test_purchasing_*.py)
```
