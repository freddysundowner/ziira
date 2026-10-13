# Testing

`make test` runs everything (about 4 minutes on PostgreSQL 16). `make lint` runs ruff, mypy (strict) and import-linter.
Tests create throw-away databases (`ziira_test_*`) and drop them afterwards.

```bash
set -a; . ./.env; set +a
.venv/bin/pytest -q tests/test_security.py                  # one file
.venv/bin/pytest -q -k "transfer and not concurrency"        # by name
.venv/bin/pytest -q --cov=ziira --cov-branch --cov-report=term-missing:skip-covered   # coverage (needs pytest-cov)
.venv/bin/pytest -q -o faulthandler_timeout=120              # print where a test hangs
```

## What is tested, by layer

| Layer | Where | What it proves |
|---|---|---|
| **Domain rules (single units)** | `ziira/modules/*/tests/` | Pure rules with no database: costing, movements, batches, transfers, counts, documents, locations, products. Includes Hypothesis **property tests** (figures always equal the sum of movements; average stays between costs paid; transfers net to zero; value never negative; negative-stock handling stays consistent). |
| **Kernel units, one at a time** | `tests/test_kernel_units.py`, `test_kernel_services.py`, `test_access_rules.py` | Approvals, users, roles, grants, numbering, reasons, settings, events, outbox (retries, give-up after 10), extension sockets, audit chain tampering, password and token helpers, client address, every CLI command and its errors. |
| **Each unit on its own** | `tests/test_units_alone.py`, `test_lifecycle*.py`, `test_registry.py` | All 12 modules and the plugin: enabled alone with only what they require, permissions and default roles and seeded reasons appear, row-level security is forced on every tenant table, disable keeps data, enable again seeds nothing twice, remove really deletes (the `.down.sql` scripts run), optional units are optional, events for disabled units are ignored. |
| **Module flows through the API** | `tests/test_products_*.py`, `test_inventory*.py`, `test_adjustments.py`, `test_transfers.py`, `test_counts.py`, `test_stock_events.py`, `test_stock_verify.py` | The business rules end to end: documents and their statuses, approvals, scope, costs hidden without `stock.cost`, FEFO, negative stock, cross-company mixing refused, inactive things refused. Shared setup: `tests/stock_helpers.py`. |
| **Permissions** | `tests/test_permissions.py`, `test_inventory_permissions.py` | Every default role against every inventory action; branch/company/tenant scope; no escalation. |
| **Security** | `tests/test_security.py` | Forged, damaged, expired and meaningless tokens; refresh replay; sessions ended on password change; garbage and cross-tenant API keys; no user enumeration; injection-style logins; huge passwords; admin endpoints closed to ordinary roles; ids from another tenant never accepted. |
| **Robustness (fuzzing)** | `tests/test_robustness.py`, `tests/fuzz.py` | A schema-driven fuzzer builds a valid request for every endpoint from the OpenAPI description and changes one value at a time (huge and non-finite numbers, NUL bytes, odd Unicode, wrong types, missing/unknown fields, bad ids, bad paging). Rule: **no input may cause a server error**. |
| **Concurrency** | `tests/test_concurrency.py`, `test_stock_properties.py`, `test_lifecycle_more.py` | Simultaneous requests: a document is submitted/dispatched/decided once; numbers are unique and gap-free; one count per location; opening stock once; the last unit is sold once (proven to fail if the row locks are removed); no deadlocks; duplicate creations leave exactly one. |
| **The books** | `tests/test_finance_*.py`, `ziira/modules/finance/tests/` | Posting from stock, sales and returns (every movement type, transfers through in-transit, atomic with the operation); periods, closing and redirects; manual journals, approval and reversals; posting rules, accounts, reports reproducible for past dates, branch-limited reading; Hypothesis: any history keeps the books balanced and equal to the stock ledger; races on first setup and numbering. |
| **Payments and M-Pesa** | `tests/test_payments_*.py`, `ziira/modules/payments/tests/` | Parsing and matching rules (Hypothesis: matched amounts never exceed either side); payments, C2B and statement import once; exact-reference, account-number and rule matching with undo; the STK prompt (job, signed callback, duplicates, cancel, timeout, status check, refusal, outage) against a fake provider and the Daraja provider against a mocked Safaricom; daily close, reopening through approval; settlements and cash deposits posting to the books; races on duplicate callbacks and on one transaction offered to several payments. |
| **Point of sale** | `tests/test_pos_*.py`, `tests/test_pricing.py`, `ziira/modules/pos/tests/` | Line money, VAT, change and refunds in parts (Hypothesis: a line returned in any parts gives back exactly what it sold for); sales end to end (stock, cost, payments, overrides, voids, returns, approval); tills (X/Z reports, variance posting); price lists with history; **offline sync**: a day offline lands once, repeating or cutting off or sending at once changes nothing, bad operations are kept whole, conflicts are accepted and flagged, device and person both checked; races (no overselling, gap-free numbers, void against return, sale against till close) and a randomized run that keeps sales, payments, stock and the books in agreement. |
| **Purchasing** | `tests/test_purchasing_*.py`, `ziira/modules/purchasing/tests/` | Costs and VAT, the three-way match, ageing and validation (Hypothesis: gross = net + tax to the cent); suppliers and the guarded change of bank details (two people, approval, encrypted, masked); requests and orders with approvals; partial receipts, never more than ordered, costed at the order, landed cost, supplier price history; bills that match, price variance, exceptions needing someone else, billing the same goods twice, expense bills, cancelling frees the invoice number; paying in parts; every posting checked against the books; races (last units received once, the same goods billed once, payments never exceed what is owed, duplicate suppliers and invoice numbers); database guards; a random history keeps stock, payables and "goods received not invoiced" in agreement with the ledger; corrections: reversing payments (through Purchasing and directly in Payments) and bills, goods sent back and replaced, credit notes (at cost, at another price, expenses), landed-cost invoices, simultaneous returns, credit notes, reversals and payments, and a random history with returns, credits and reversals checked against the books. |
| **Database guarantees** | `tests/test_database_rules.py` | Immutability, balanced journals, per-tenant logins, drop/suspend. |
| **Architecture** | `tests/test_architecture.py` + import-linter | Units import only the SDK and each other's `public.py`; manifests match the code. |
| **Web app** | `frontend/` (`make web-check`) | Module registry rules, translations in step, types generated from the API. |

## Bugs this found (all fixed, each with a test)

- Numbers that cannot be stored (1e20, NaN, infinity, too many digits) caused server errors; request bodies now use
  column-sized number types (`ziira.sdk.Quantity`, `UnitCost`, `Amount`, `Rate`) and the ledger refuses amounts that
  would overflow.
- `limit`/`offset` of lists accepted negative or enormous values (server error); NUL characters in text did too.
- A signed token with missing or malformed fields caused a server error instead of 401.
- Two people starting a count at once, or posting opening stock at once, both succeeded (races); now a lock plus a
  database index (`stock_count_one_open`).
- Product search treated `%` and `_` as wildcards.
- Whitespace-only names, unknown eTIMS tax types, malformed emails and phone numbers were accepted.
- Passwords of any length were hashed (a CPU burn); now at most 1,024 characters.
- A corrupt company setting would have stopped sales; it now falls back to the default (and is logged).
- Removing a disabled owner's grant was refused when one other owner existed.
- Expired approval requests were still listed as pending.
- Constraint wording from the database leaked in 409 replies; replies are now generic.
- `NaN` received or counted quantities raised an arithmetic error instead of a validation error.

## Not covered on purpose

- Rate limiting / lockout on sign-in and MFA (phase 11).
- Anything about modules that are only skeletons (POS, Payments, CRM, Purchasing, Finance, People, Command Center,
  Intelligence): only their install, enable, disable and remove are tested, plus forced row-level security.
