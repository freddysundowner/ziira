# Finance and Accounting

**Status:** working for phase 3 (the ledger). Chart of accounts, posting engine, periods and closing, manual journals with
approval, reversals, posting rules as data, trial balance, general ledger and the books check are built and tested.
Not built yet: expenses, bank reconciliation, P&L / balance sheet / VAT reports, exports (phase 8); postings for supplier
bills, customer payments and payroll (when those units exist).

| | |
|---|---|
| Schema | `finance` (migrations `0001_init`, `0002_manual_journals`) |
| Requires | kernel only |
| Optional | pos, payments, purchasing, inventory, people |
| Publishes | `journal.posted`, `period.closed` |
| Subscribes | `stock.moved`, `sale.posted`, `sale.returned`, `approval.decided` (kernel) |
| Plugs into | `kernel.integrity_check` (the books check) |
| API | `/api/v1/finance` |
| Permissions | `accounts.manage`, `journal.post_manual`, `journal.approve`, `period.close`, `reports.view` (and `expenses.*`, later) |
| Default roles | Finance Manager: all · Accountant: chart, manual journals, reports · Branch Manager: reports (own branch) · Owner: all |
| Company setting | `late_posting` (`redirect` or `reject`): what happens to a document dated in a closed period |

## The rules (specification section 07)

- **Double entry, immutable.** An entry has two or more lines, each a debit or a credit; debits equal credits (checked in
  `domain/entries.py`, by the posting engine, and by a deferred database trigger at commit). Entries and lines reject
  UPDATE and DELETE. Corrections are reversing entries.
- **One place makes entries:** `services/posting.py: post_entry`. Operational units never call it: they publish documents,
  and `events.py` turns them into entries in the *same transaction*, so a sale, its stock and its books stand or fall
  together. If posting fails (no posting rule, a locked period with `late_posting = reject`), the whole operation fails.
- **Posting rules are data.** `domain/recipes.py` decides the shape of an entry (which roles on which side);
  `finance.posting_rule` says which account each role uses, seeded from `domain/chart.py` (a Kenyan SME chart) and
  changeable per company. A rule with conditions (for example only for `write_off`) beats a general one.
- **Branch dimension.** Every line carries the branch, so reports can be per branch.
- **Control accounts** (inventory, in transit, receivables, payables, M-Pesa clearing, goods received not invoiced, transfer
  clearing) are kept by their sub-ledgers: people cannot post to them by hand, and cannot switch them off.
- **Periods** are monthly, created when something is first posted into the month. `open` -> `soft_closed` (only people with
  `period.close` post manual entries; documents follow `late_posting`) -> `locked` (nothing posts; never reopened). Closing
  runs the checklist: no manual journals waiting for approval, and the stock ledger equals the inventory accounts.
- **Reversals** apply to manual entries, once each; an entry made from a sale or a stock movement is corrected in that
  document (a return, an adjustment).
- **Books check** (`ziira verify`, `kernel.integrity_check`): every entry balances, each company's debits equal its credits,
  the inventory accounts equal the stock ledger, every stock movement is posted; `--fix` posts any that are missing.

## Endpoints

| Method | Path | Does | Needs |
|---|---|---|---|
| POST | `/companies/{id}/books` | Create the chart, journals and default rules (harmless if they exist) | `accounts.manage` |
| GET, POST, PATCH | `/accounts`, `/accounts/{id}` | The chart of accounts | read: any finance permission · write: `accounts.manage` |
| GET, POST, PUT, DELETE | `/posting-rules`, `/posting-rules/{id}` | Which account each document line goes to | as above |
| GET, POST | `/periods`; GET `/periods/{id}/checklist`; POST `/periods/{id}/status` | Periods, what blocks closing, close / lock / reopen | `period.close` |
| GET | `/journal-entries`, `/journal-entries/{id}` | Read entries (a branch grant sees its branch's lines) | `reports.view` |
| POST | `/journal-entries/{id}/reverse` | Reverse a manual entry | `journal.approve` |
| POST, GET | `/manual-journals`, `/{id}`; POST `/{id}/submit` | Draft, submit (posts at once or waits for approval) | `journal.post_manual` |
| GET | `/reports/trial-balance`, `/reports/general-ledger` | Reports, reproducible for any past date | `reports.view` |

Manual journals use the kernel's approval matrix (`doc_type` `manual_journal`); the approver must hold the role named in the
rule and `journal.approve`.

## Events other units publish (payloads: `services/event_postings.py`)

| Event | Entry |
|---|---|
| `stock.moved` (Inventory, every movement) | inventory, cost of goods sold, shrinkage, goods received not invoiced, transfers via in-transit |
| `sale.posted` (POS) | money received or owed (cash, M-Pesa, card, credit to a customer, other) against sales and VAT output |
| `sale.returned` (POS) | sales returns and VAT output reversed against the refund |

The cost of goods sold is not in `sale.posted`: the sale's stock movements publish `stock.moved`, which posts it.

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     posting (the engine), books, accounts, posting_rules, periods, manual_journals, entries, reports,
              event_postings, verify, access
domain/       entries, periods, chart, recipes, rules: no database or HTTP
repository/   models.py and finance_repo.py
events.py     handlers for subscribed events
hooks.py      the books check (kernel.integrity_check)
public.py     the only file other units may import (nothing yet: units talk to Finance through events)
tests/        domain unit and property tests (the API and database tests are in /tests)
```
