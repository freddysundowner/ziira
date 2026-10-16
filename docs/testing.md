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
| **The books** | `tests/test_finance_*.py`, `ziira/modules/finance/tests/` | Posting from stock, sales and returns (every movement type, transfers through in-transit, atomic with the operation); periods, closing and redirects; manual journals, approval and reversals; posting rules, accounts, reports reproducible for past dates, branch-limited reading; Hypothesis: any history keeps the books balanced and equal to the stock ledger; races on first setup and numbering. **Phase 8:** `test_finance_reports.py` (P&L by branch, balance sheet, cash flow and VAT checked to the cent against known postings, CSV, journal export in three layouts, formula-injection defusing, branch-limited reading), `test_finance_expenses.py` (post, approve, reject, reverse, scope), `test_finance_reconciliation.py` (full month-by-month cycle, M-Pesa account, statement matching, period-close checklist); Hypothesis: the balance sheet balances and cash flow reconciles for any books, a ledger line is matched at most once. |
| **Payments and M-Pesa** | `tests/test_payments_*.py`, `ziira/modules/payments/tests/` | Parsing and matching rules (Hypothesis: matched amounts never exceed either side); payments, C2B and statement import once; exact-reference, account-number and rule matching with undo; the STK prompt (job, signed callback, duplicates, cancel, timeout, status check, refusal, outage) against a fake provider and the Daraja provider against a mocked Safaricom; daily close, reopening through approval; settlements and cash deposits posting to the books; races on duplicate callbacks and on one transaction offered to several payments. |
| **Point of sale** | `tests/test_pos_*.py`, `tests/test_pricing.py`, `ziira/modules/pos/tests/` | Line money, VAT, change and refunds in parts (Hypothesis: a line returned in any parts gives back exactly what it sold for); sales end to end (stock, cost, payments, overrides, voids, returns, approval); tills (X/Z reports, variance posting); price lists with history; **offline sync**: a day offline lands once, repeating or cutting off or sending at once changes nothing, bad operations are kept whole, conflicts are accepted and flagged, device and person both checked; races (no overselling, gap-free numbers, void against return, sale against till close) and a randomized run that keeps sales, payments, stock and the books in agreement. |
| **Purchasing** | `tests/test_purchasing_*.py`, `ziira/modules/purchasing/tests/` | Costs and VAT, the three-way match, ageing and validation (Hypothesis: gross = net + tax to the cent); suppliers and the guarded change of bank details (two people, approval, encrypted, masked); requests and orders with approvals; partial receipts, never more than ordered, costed at the order, landed cost, supplier price history; bills that match, price variance, exceptions needing someone else, billing the same goods twice, expense bills, cancelling frees the invoice number; paying in parts; every posting checked against the books; races (last units received once, the same goods billed once, payments never exceed what is owed, duplicate suppliers and invoice numbers); database guards; a random history keeps stock, payables and "goods received not invoiced" in agreement with the ledger; corrections: reversing payments (through Purchasing and directly in Payments) and bills, goods sent back and replaced, credit notes (at cost, at another price, expenses), landed-cost invoices, simultaneous returns, credit notes, reversals and payments, and a random history with returns, credits and reversals checked against the books. |
| **Customers and receivables** | `tests/test_crm.py`, `test_credit_sales.py`, `test_sales_documents.py`, `test_receivables.py`, `test_sales_properties.py` | Customers, credit changes that need approval, leads and follow-ups; credit sales end to end (limit, hold, part cash, group prices, offline); customers paying (oldest first, named, over-payment refused, cash at the till, reversal in either place); credit notes and voids of credit sales; quotation -> order -> partial deliveries -> invoice -> payment with every posting checked against the books; ageing, statements, balances, reminders; races (credit limit, payments, deliveries, credit notes, payment against void); a random history checked against the customer ledger, the receivable account, the stock and the trial balance. |
| **End to end** | `tests/test_end_to_end.py`, `scripts/smoke_live.py` | One USD business with British phone numbers through the whole system over HTTP: buy, receive, bill, pay; cash, mobile money, card and credit sales; replayed, voided and returned sales; till and cash deposit; settlement; expense; reports that must agree with each other (trial balance, P&L, VAT, balance sheet, cash flow); bank reconciliation; payroll; sub-ledgers and the stock ledger equal their control accounts; `ziira verify`. The same journey runs against a **live server** with `scripts/smoke_live.py <url> <workspace> <email> <password>` (use a scratch workspace). |
| **People and payroll** | `tests/test_people_*.py`, `ziira/modules/people/tests/` | Payroll **golden cases worked out by hand** for every band, cap, minimum, part month, unpaid leave, overtime, benefit and non-resident case, with Hypothesis (net pay never negative, more pay never means less net, bands against a slow calculation); the whole lifecycle with the journal entry checked to the cent by branch; separation of duties (pay, bank details, rules, run approval); a run whose inputs changed cannot be approved; payroll privacy by role. |
| **Messaging and recurring tasks** | `tests/test_notifications.py`, `test_reminders_sending.py`, `test_periodic.py`, `test_advances.py`, `ziira/plugins/messaging/tests/` | The notification queue (sent in the background, once; deduplicated; validated; opt-outs per channel or all; retried when a gateway is down, not when it refuses; gives up after five tries; skipped and flagged with no channel); the providers against pretend gateways (SMTP, Africa's Talking, WhatsApp Cloud: request shapes, refusals, outages); reminders by request, in a batch and by the daily task, with the settings that drive them; recurring tasks (claimed once per interval, failures recorded, units that are off skipped); quotations expiring by themselves; advance payments (held, applied, refunded, reversed, credit widening the limit) with the customer ledger check. |
| **Plugin kit, public API, webhooks** | `tests/test_plugin_kit.py`, `test_api_keys.py`, `test_public_api.py`, `test_webhooks.py` | The scaffold passes `ziira plugin check` and its own tests; deliberately bad plugins (no RLS, float money, kernel import, unguarded route, foreign keys, raw SQL on other schemas, network at import) fail with a clear fix; pack/install-archive (tampering, wrong hash, unsafe paths); production refuses unreviewed or changed plugins; API key scopes, read-only, company limits, public-only, rate limit (429 + Retry-After), expiry, rotation, usage; the public OpenAPI subset and deprecation headers; webhook signing checked against an independent verifier (and the snippet in docs/webhooks.md), retries and backoff with a fake transport, 410 disabling, SSRF refusals and re-resolution, delivery log and redelivery, permissions, isolation, payload minimisation, purge, privacy provider. `ziira.sdk.testing` is the kit plugin authors use. |
| **Database guarantees** | `tests/test_database_rules.py` | Immutability, balanced journals, per-tenant logins, drop/suspend. |
| **Architecture** | `tests/test_architecture.py` + import-linter | Units import only the SDK and each other's `public.py`; manifests match the code; **no country, currency, tax authority or vendor name in `ziira/modules` or `ziira/kernel`** (rule 15; leftovers are in the test's `ALLOWED` table with a reason). |
| **Country packs and provider plugins** | `tests/test_country_packs.py`, `ziira/plugins/*/tests` | The country list, a pack chosen at registration (and the international fallback), seeding that is idempotent and never overwrites, the upgrade step that switches on a provider plugin; each pack's data files parse with the owning unit's own rules; the M-Pesa formats and provider against a mock Safaricom. |
| **Web app** | `frontend/` (`make web-check`) | Module registry rules, translations in step, types generated from the API. |

## Real-browser journeys (`make e2e`)

Eighteen journeys drive the web app in Chromium (Playwright) against a **throwaway stack that the run starts and removes**:
`e2e/run.sh` creates scratch PostgreSQL databases (`ziira_e2e_master`, `ziira_e2e_template`, `ziira_e2e_t_*`, logins `ze2e_*`:
never the dev, demo or pytest ones), installs every unit, starts the API on `:8765` (`ZIIRA_ENV=development`, two-step sign-in
off, the platform's fake email so the registration response carries `dev_token`), `ziira worker` (imports and other
background jobs), and the production build of the web app served by `vite preview` on `:4175` (its `/api` proxy follows
`ZIIRA_API_URL`), runs the tests, then stops everything and drops the databases. A file lock (`ziira-e2e.lock`) makes a
second run wait. Nothing touches `demo-hardware` or port 8000/5173.

```bash
make e2e-setup                        # once: npm ci in e2e/ and the Chromium download
make e2e                              # everything (about 8 minutes)
bash e2e/run.sh tests/j03             # one journey; any Playwright arguments work
E2E_SERVE=1 bash e2e/run.sh           # just start the stack (web :4175, api :8765) and keep it for poking around
```

| Journey | Covers |
|---|---|
| J1 `j01-register-and-sign-in` | two-step registration form, verification link, signed in; sign out, wrong password, sign in; forgot-password link, new password, old one refused |
| J2 `j02-catalogue-and-stock` | unit, tax code, price list; products with a price; location, opening stock; stock page; adjustment with a reason; the API agrees |
| J3 `j03-sell` | open a till, cash sale with change, hold and resume, mobile-money sale refused then retried once an account exists, void, return with a cash refund, close with a counted amount (variance), cash refund refused on a closed till; stock afterwards |
| J4 `j04-buy` | supplier, order (approval if asked), receive into stock, bill from the receipt checked, paid; payables |
| J4b `j04b-pay-without-account` | a business with no payment account: paying a supplier says so, offers to add a bank account in place (mobile money points to Payments), then the payment goes through |
| J5 `j05-customers-and-credit` | customer, credit limit, credit sale over the limit refused then allowed, payment received, ageing |
| J6 `j06-money` | journal lists the sale, trial balance balances, P&L income equals sales less returns (from the sales API), expense, reconciliation started |
| J7 `j07-people` | employee; basic pay proposed by one person and approved by another; a rule defined and verified by someone else; a payroll run prepared by one and approved by another; the payslip (1,000.00 less 5% = 950.00) |
| J8 `j08-admin` | a user with the Cashier role for one branch sees only the till and gets "does not exist" for finance, payroll and admin; a setting persists; an API key's secret is shown once |
| J8b `j08b-branch-scoping` | a second branch added and edited in Settings > Organisation; a store, a till and a branch-scoped manager for it; a sale and a short till at each branch; the scoped manager sees only her branch's sales, stock, findings and Command Center figures (screens and API), the other branch's ids answer 403 or 404, the owner sees both |
| J9 `j09-intelligence-and-command` | a check's limit lowered in the UI, the checks run from the UI, the finding is acknowledged and explained; the Command Center's sales equal the day's sales; a brief preview |
| J11 `j11-offline-till` | barcode set on the product page; offline sales (scan), reload offline, hold offline, reconnect: each sale once with the right total even when an answer is lost, held sale uploaded and resumed; a browser without storage refuses offline selling |
| J10 `j10-import` | CSV upload, column matching, one bad row flagged, three imported by the worker, the reconciliation; the products exist |
| J12 `j12-two-step-sign-in` | the owner requires two-step verification for powerful roles; a second user is stopped until she sets it up (the code is made in the test from the secret on screen, RFC 6238), signs in with a code, with a backup code (once only), meets the wrong-code message, and is locked out after repeated wrong codes (the real throttle) |
| J13 `j13-language-and-theme` | Swahili: menu and headings translated, no screen shows a raw key, `undefined`, `NaN` or `{{placeholder}}`; dark mode: the contrast scan on the main pages and no element with a light background of its own; both choices survive a reload |
| J14 `j14-phone-width` | 390 x 844: the menu is a drawer, the main lists never scroll the page sideways, a form in a drawer fits and saves, the till terminal sells for cash from search to "Sale complete" |
| J15 `j15-printing` | receipt, Z report, supplier statement and payslip in print mode: menu, top bar and buttons are gone, the document is there, and the browser makes a PDF with content from it |
| J16 `j16-support-and-privacy` | support access given and ended in the UI; a platform operator (created by `ziira operator create` in `run.sh`, signing in with a code from its second factor) cannot open the business without a grant, opens a read-only session with one (looking works, changing is refused), the banner and the access log show it, ending the grant ends the session; a privacy request recorded, searched and exported as a JSON file |

Every test also fails on an uncaught page error, a `console.error`, a request that failed, or any answer of 500 or more, and
runs an `axe` accessibility scan (WCAG A and AA) on the main screens: serious or critical violations fail the test and are
appended to `e2e/test-results/a11y.txt`. A failing test prints the last API calls and every 4xx answer of the run. Screenshots
of each journey's last screen go to `e2e/screenshots/` (gitignored), traces of failures to `e2e/test-results/`.

How the tests are written: one business shared by J2-J10 is registered in `global-setup.ts` (J1 registers its own through the
form); each journey creates what it needs with unique names, using the API (`e2e/lib/seed.ts`) for plumbing that is not under
test and the browser for the subject, so the journeys can run alone or in any order. "Someone else" (separation of duties) is a
second browser window signed in as the shared business's second user (`second(account)`). Use `lbl("Name")` for labels (it
matches with or without the required star); no fixed sleeps. Findings and what is still open: `docs/e2e-findings.md`.

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
