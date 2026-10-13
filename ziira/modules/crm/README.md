# CRM and Customers

**Status:** working for phase 6: customers and contacts, credit limits and terms with history and approval, leads with
sources and conversion, and follow-up activities. Statements, ageing and reminders about what customers owe live in POS
(which owns the invoices); reminders are recorded, and sending them by WhatsApp, SMS or email arrives with notifications.

| | |
|---|---|
| Schema | `crm` (migrations `0001_init`, `0002_phase6`) |
| Requires | kernel only |
| Optional | pos, payments |
| Publishes | `customer.created`, `lead.created`, `lead.converted`, `customer.credit_limit_changed` |
| Subscribes | `approval.decided` (kernel): a credit limit increase |
| API | `/api/v1/crm` |
| Permissions | `customers.view`, `customers.manage`, `credit.approve`, `leads.manage` |
| Default roles | Finance Manager: all · Branch Manager and Sales Rep: view, manage, leads · Cashier and Accountant: view |

## The rules

- **Customers** belong to a company (not a branch): a grant at any branch of the company is enough to work with them. Phone
  numbers are stored as `2547XXXXXXXX`; the code is made for you (`CUS-000001`) unless you choose one. A customer starts
  with no credit.
- **Credit is versioned.** The limit and payment terms are changed with `POST /customers/{id}/credit` and a reason; every
  position is kept as history. *Lowering* the limit, or changing only the terms, applies at once. *Raising* it is approved by
  someone else (document type `credit_limit_change`); with no approval rule configured only a person with `credit.approve`
  can raise it, so a salesperson cannot give their own customer credit.
- **Customer groups** (a free-text label) pick the price list a customer buys from (Products: a price list with a
  `customer_group`).
- **Leads** go new -> contacted -> qualified, or lost (with a reason; a lost lead can be reopened). Converting a lead makes a
  customer (and, for a business, its contact) and records the link. A lead needs a phone number or an email address.
- **Activities** (call, visit, message, meeting, task) are follow-ups about a lead or customer, with an owner and a due date;
  `GET /activities?mine=true&open_only=true` is a person's to-do list.
- POS reads customers and their credit through `public.find_customer(s)`; it never reads CRM's tables.

## Layout

```
api/          routes.py, schemas.py
services/     customers (+ contacts, credit), leads (+ sources, activities), access
domain/       rules.py: phone, email, PIN, credit and lead moves (pure, unit-tested)
repository/   models.py, crm_repo.py
events.py     approval.decided
public.py     CustomerView, find_customer, find_customers
tests/        domain tests; flows are in the top-level tests/test_crm.py
```
