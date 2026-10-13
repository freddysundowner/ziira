# Purchasing and Suppliers

**Status:** working for phase 7: suppliers (with guarded bank details), purchase requests and orders, goods receipts,
supplier bills with the three-way match, payment of bills, and what is owed to suppliers by age. Not built yet: returning
goods to a supplier and supplier credit notes, reversing a posted bill, landed-cost invoices that clear the landed part of
"goods received not invoiced", pulling supplier invoices from eTIMS (phase 5), supplier statements reconciliation.

| | |
|---|---|
| Schema | `purchasing` (migrations `0001_init`, `0002_phase7`) |
| Requires | products |
| Optional | inventory (receiving goods), finance (expense accounts and the books), payments (paying bills) |
| Publishes | `po.approved`, `goods.received`, `bill.posted`, `bill.match_exception`, `supplier.bank_changed`, `supplier.price_changed`, `supplier.paid` |
| Subscribes | `approval.decided` (kernel): purchase requests, orders, bills and supplier bank changes |
| API | `/api/v1/purchasing` |
| Permissions | `suppliers.manage`, `supplier.bank_edit`, `supplier.bank_confirm`, `po.create`, `po.approve`, `goods.receive`, `bills.manage`, `bills.approve`, `bills.pay`, `purchasing.view` |
| Default roles | Finance Manager: all · Branch Manager: view, order, receive · Storekeeper: view, receive · Accountant: view, suppliers, bills |
| Company setting | `bill_match_tolerance_percent` (default 2) |
| Reason list | `bill_exception` |

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

## Layout

```
api/          routes.py, schemas.py
services/     suppliers (+ bank details), orders (+ requests), receipts, bills (+ payment, payables), access, common
domain/       rules.py: costs and VAT, the match, order status, ageing, validation (pure, unit-tested)
repository/   models.py, purchasing_repo.py
events.py     approval.decided
public.py     supplier_balance
tests/        domain tests; flows are in the top-level tests/ (test_purchasing_*.py)
```
