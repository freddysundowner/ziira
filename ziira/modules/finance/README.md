# Finance and Accounting

**Status:** working for phases 3 and 8. The ledger (chart of accounts, posting engine, periods and closing, manual journals
with approval, reversals, posting rules as data, trial balance, general ledger, books check) and, on top of it, the
**financial statements** (profit and loss consolidated or by branch, balance sheet, cash flow summary, VAT summary), their
**CSV downloads**, the **journal export** for the accountant's software (generic, QuickBooks, Sage; account mapping per
company), **expenses** with approval, and **bank reconciliation**. Payroll postings arrive with People (phase 9).

| | |
|---|---|
| Schema | `finance` (migrations `0001_init`, `0002_manual_journals`, `0003_account_mapping`, `0004_expenses`, `0005_bank_reconciliation`) |
| Requires | kernel only |
| Optional | pos, payments, purchasing, inventory, people |
| Publishes | `journal.posted`, `period.closed`, `expense.approved`, `reconciliation.completed` |
| Subscribes | `stock.moved`, `sale.posted`, `sale.returned`, `approval.decided` (kernel) |
| Plugs into | `kernel.integrity_check` (the books check) |
| API | `/api/v1/finance` |
| Permissions | `accounts.manage`, `journal.post_manual`, `journal.approve`, `period.close`, `reports.view`, `expenses.submit`, `expenses.approve`, `bank.reconcile` |
| Default roles | Finance Manager: all · Accountant: chart, manual journals, reports, expenses (submit), bank reconciliation · Branch Manager: reports and expenses (own branch) · Owner: all |
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
| GET | `/reports/profit-and-loss` (`by_branch`, `branch_id`), `/reports/balance-sheet`, `/reports/cash-flow`, `/reports/vat-summary` | Statements; add `format=csv` to download | `reports.view` (a branch grant sees its branch) |
| GET | `/exports/journal?format=generic\|quickbooks\|sage` | The journal lines of a period as CSV | `reports.view` |
| GET, PUT, DELETE | `/account-mappings`, `/account-mappings/{account_id}` | What the accountant calls each account | read: any finance permission · write: `accounts.manage` |
| POST, GET | `/expenses`, `/expenses/{id}`; POST `/{id}/submit`, `/{id}/reverse` | Draft, submit (posts at once or waits for approval), reverse | `expenses.submit` · reverse: `expenses.approve` |
| POST, GET, DELETE | `/bank-reconciliations`, `/{id}`; POST `/{id}/clear`, `/{id}/suggestions`, `/{id}/complete` | Reconcile an account to a statement | `bank.reconcile` |

Manual journals use the kernel's approval matrix (`doc_type` `manual_journal`); the approver must hold the role named in the
rule and `journal.approve`.

## Statements and exports

- **They read the journal lines**, so each is reproducible for any past date and reconciles to the books by construction
  (`balanced` and `reconciles` in the answers prove it). `domain/statements.py` is plain arithmetic over account totals.
- **Profit and loss:** income, less *cost of sales* (cost of goods sold, shrinkage, purchase price variance) = gross profit,
  less the other expenses = net profit. `by_branch=true` adds a statement per branch (lines with no branch are shown
  separately); `branch_id` restricts to one. **Balance sheet:** assets, liabilities, equity, and the profit that has not been
  closed into equity on its own line, so assets always equal liabilities plus equity. **Cash flow:** the cash, bank, M-Pesa
  and card accounts: opening balance, what moved them by kind of document, closing balance. **VAT summary:** VAT charged
  (account 2200) less VAT paid (1300) with the net sales behind it: the figure for the VAT return. Rates come from the tax
  codes entered by hand on products; there is no per-rate split because the ledger holds one VAT account.
- **CSV** cells that start with `= + - @` are prefixed with an apostrophe so a spreadsheet never runs them as formulas.
- **Journal export:** `generic` (every column), `quickbooks` (QuickBooks Online journal import: `*JournalNo`, date as
  dd/mm/yyyy, account name) and `sage` (Sage 50 journal import: `JD`/`JC`, nominal code). Each account is exported under its
  *mapping* (external code and name) when one is set. These two layouts were written from the products' public import
  documentation and **have not been imported into the real software**: have the accountant try a small file first.

## Expenses

A cost paid at once from cash, bank, M-Pesa or card (`paid_from`); `amount` is everything paid and `tax_amount` the VAT inside
it. Posting: Dr the expense account (amount less VAT), Dr VAT input, Cr the account the money came from. Costs bought on
credit go through Purchasing's supplier bills so accounts payable equals the supplier ledger. `draft` -> `submit` -> posted
at once, or `pending_approval` when an approval rule (`doc_type` `expense`) matches the amount, then posted by the approver
(`expenses.approve`) or rejected. A posted expense is cancelled by `reverse` (a mirror entry, with a reason). The receipt is
recorded by reference (its number or file name); storing the file itself waits for the files service.

## Bank reconciliation

For a bank, M-Pesa or card account: start with the statement's date and closing balance, then *clear* the ledger lines that
appear on the statement (by id, or `until` a date for everything settled before the statement began). It can be completed
only when the cleared lines add up to the statement's balance (`difference` is zero); the lines still not cleared are the
reconciling items (a deposit in transit, a cheque not yet presented). Upload the statement's lines (JSON or CSV; signed
amounts, or paid-in and withdrawn columns) to get suggested matches, one to one by amount, the same reference first, then the
nearest date within five days; `apply` clears them. Statement lines with nothing in the books (bank charges) are listed so
they can be entered as an expense or manual journal first. One reconciliation is open per account, a completed one is final
and its lines are never cleared again, and a period with one still open cannot be closed.

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
