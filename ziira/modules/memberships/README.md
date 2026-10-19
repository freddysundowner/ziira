# Memberships and Recurring Invoices

Membership plans, session packages with a credits ledger, and invoices that repeat on a schedule. Full description, the public
functions other units call, events, permissions and limits: [`docs/memberships.md`](../../../docs/memberships.md).

* `domain/` pure rules (billing periods, proration, credit allocation, quiet hours), property-tested.
* `services/` one file per use case; `billing.py` is the exactly-once period invoicing, `invoicing.py` the only place that asks Point of Sale for an invoice.
* `jobs.py` the hourly recurring tasks; `public.py` the functions other units import.
