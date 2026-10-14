# Demo data: a business that looks alive

`scripts/seed_demo_rich.py` fills a **development** business with about 90 days of believable trading, so that every
screen (Command Center, Findings, reports, POS, purchasing, payroll, imports) has something to show. It is for demos,
screenshots and manual testing. It is not a load test (that is `scripts/seed_load.py`, `docs/performance.md`).

## Run it

Time: the full run took about 6.5 minutes on a busy development Mac (`--scale small` about 3.5 minutes, the `tiny` scale of
the test about 25 seconds). Most of it is the API doing real work for each of the 1,800 sales; the machine's other jobs
(tests, a worker) slow it down.

```bash
make db-up                                                  # PostgreSQL in Docker, if it is not running
.venv/bin/python scripts/seed_demo_rich.py                  # fills demo-hardware, full scale (90 days, about 1,800 sales)
.venv/bin/python scripts/seed_demo_rich.py --scale small    # 45 days, about 600 sales: a faster look (about 3 minutes)
.venv/bin/python scripts/seed_demo_rich.py --tenant demo-sales   # another business whose code starts with "demo"
.venv/bin/python scripts/seed_demo_rich.py --reset --confirm demo-hardware   # start over (see below)
```

The business must exist (`bash scripts/run_local.sh` makes `demo-hardware`; or `ziira create-tenant`). The script
turns on the units it needs (POS, CRM, Finance, Purchasing, People, Intelligence, Command Center, Imports), creates the
rest through the API, and ends by running `ziira verify`, the trial balance and the Intelligence tasks, then **checks
that every planted story produced its finding** and exits non-zero (naming the missing ones) if one did not.
Runtime on this Mac: see "Runtime" below. It prints progress, then a summary of what it made, the findings per check and
the Command Center figures.

Safety rules the script enforces:

* it refuses `ZIIRA_ENV=production`;
* it refuses any business whose code does not start with `demo` unless you add `--i-know`, and refuses `aluta-*` always;
* running it twice on a business it already filled does nothing (it says so and exits 0);
* `--reset` drops and recreates the business with `ziira drop-tenant` / `ziira create-tenant`, and only for the code
  `demo-hardware` or a code starting with `demo-`, and only with `--confirm <the same code>`. It never touches another
  business.

If a run stops half way (a crash, Ctrl-C) the business is left half filled: use `--reset` to start over. (Re-running
without `--reset` finishes the set-up, but the days already simulated cannot be resumed.)

Before it adds anything the script runs `ziira verify` and, if the business is not consistent (the old demo posted its
opening stock before Finance was switched on), `ziira verify --fix`; it also tops up the default roles with the permissions
their units define (an old demo business can lack, for example, the Cashier's till permission). If a worker (`ziira worker`) is
running on your machine it also serves this business and may run the Intelligence tasks while the history is half made, so
the script clears findings, baselines, figures and briefs and runs the tasks again once the data is complete.

## Logins

Every login uses the password **`demo-pass-123`** (the domain is `@<business code>.test`; for `demo-hardware`
that is `@demo-hardware.test`).

| Role | Name | Login | Where |
|---|---|---|---|
| Owner | Demo Owner | `owner@demo-hardware.test` | everywhere |
| Finance Manager | Faith Wambui | `finance@demo-hardware.test` | the company |
| Accountant | Peter Kariuki | `accountant@demo-hardware.test` | the company |
| HR | Hannah Achieng | `hr@demo-hardware.test` | the company |
| Sales Rep | Samuel Ndegwa | `salesrep@demo-hardware.test` | the company |
| Storekeeper | Joseph Karanja | `storekeeper@demo-hardware.test` | Thika |
| Branch Manager | Grace Njeri | `manager.thika@demo-hardware.test` | Thika |
| Branch Manager | Daniel Omondi | `manager.juja@demo-hardware.test` | Juja |
| Branch Manager | Moses Mutua | `manager.ruiru@demo-hardware.test` | Ruiru |
| Cashier | Lucy Chebet | `cashier.thika@demo-hardware.test` | Thika |
| Cashier | Esther Wafula | `cashier.juja@demo-hardware.test` | Juja |
| Cashier | Brian Mwangi | `cashier2.juja@demo-hardware.test` | Juja (story 1) |
| Cashier | Ruth Kiptoo | `cashier.ruiru@demo-hardware.test` | Ruiru |

Each branch has two tills: counter 1 (`D1`, the cashier's) and the manager's counter (`D2`, used for discounts and
bigger customers).

## What exists

All counts are for `--scale full`; the script prints the real ones at the end.

* **The business**: Demo Hardware Ltd, a hardware retail and distribution company in KES, time zone `Africa/Nairobi`,
  three branches (Thika, Juja, Ruiru) each with a store location, a till cash account, a mobile money account, a card
  terminal account and two tills; a company bank account; the standard chart of accounts plus fuel, cleaning, security and
  repairs accounts.
* **Reference data (as data, not code)**: 8 units of measure; 4 tax codes (standard 16%, zero, exempt, reduced 8%; plausible
  fixtures, a business enters its own); 6 categories; 45 products with barcodes, a Retail (default) and a Wholesale
  price list; reason codes (the seeded ones plus four of the business's own); approval rules for purchase orders
  (from 150,000), supplier bills (from 250,000), credit limit changes (from 200,000), stock adjustments (from 5,000),
  expenses (from 30,000), sales returns (from 12,000) and supplier bank details (always). The old five-product demo's
  products (`CEM-50KG`, `ROOF-G30`, `NAIL-4IN`, `PAINT-W4L`, `DELIVERY`) are part of the list (46 products with `DELIVERY`,
  a service). Prices are the shop's, tax included, about 18% over cost (cement is sold close to cost); the wholesale list is
  7% under retail.
* **Customers and suppliers**: 25 customers (shops, contractors, a school, NGOs; credit limits 60,000 to 500,000, terms
  14 to 60 days, some in the wholesale group) and 5 more brought in by a sample import from an old spreadsheet (one row
  refused, one already known: see Imports); 12 suppliers with bank details proposed and confirmed (two proposed, not yet
  confirmed: the 9th and 12th, which the business has not bought from).
* **Ninety days of trading**: about 1,800 counter sales (cash, mobile money with M-Pesa codes, card, split payments and
  credit) with the weekday and payday pattern of a real shop (busier Saturdays, a bump around the 25th to the 3rd), tills
  opened and closed every day with small cash differences, voids, returns and discounts; about 90 invoices to bulk customers
  with receipts and an ageing; about 135 purchase orders (a quarter started as purchase requests) with deliveries, supplier
  bills and payments (some part paid, some overdue); 11 stock transfers between branches (one still on the road), a stock
  count with differences, stock adjustments (one above the approval limit, approved by Finance), about 135 expenses with
  approvals, weekly cash deposits and mobile money settlements to the bank, provider statements loaded and matched, about 230
  daily closes (not on settlement Mondays), and a bank reconciliation left open. The latest run made 1,819 sales (the last
  few are today, on tills that are still open), 436 till sessions, 4,674 stock movements, 7,278 journal entries and 8,873
  audit entries, and it came to a gross margin of 27% and a small profit for the month.
* **People**: 14 employees across the branches with approved pay terms and payment details, pay components, three
  statutory rules defined as **data** (a retirement fund percentage, a health levy percentage and progressive income tax
  bands; invented generic figures, verified by a second person), attendance for the last weeks, leave (approved, rejected
  and two waiting), two payroll runs calculated, approved by the owner (not the person who prepared them), posted and paid,
  and a third being prepared.
* **CRM**: 15 leads with follow-ups (some overdue), two converted or lost; a credit limit increase waiting for approval.
* **Intelligence and Command Center**: baselines refreshed, all checks run, pulse figures stored, a daily brief made for
  the owner.

## How the history is made (and what is not "real")

Everything goes through the real API, signed in as the person who would do it (permissions, numbering, audit log, events,
posting to the books, immutability). The API only knows "now", so the script runs each business day *as if it were today*
and then moves what that day made to its real date (timestamps stretched over 07:45 to 20:15, dates moved back by the number
of days). The pass is done once at the end, with the tables' immutability triggers switched off **for that pass only**
(and switched back on, which `tests/test_seed_demo_rich.py` checks). It changes no amount, number or link between records,
and the proof is that `ziira verify` (books, stock ledger against the books, customer ledger) and the trial balance are clean
afterwards; the script fails if they are not.

Things that are not done through a service, because no endpoint exists: the two extra branches, product categories and
barcodes (small direct writes, like an import). Things worth knowing: the audit log's own time stamps are moved too (its hash
chain does not include the time, so it still verifies); mobile money and card takings are matched to provider statements the
script itself writes from the recorded payments, with a few deliberate gaps (stories below); the business settles M-Pesa
weekly, so the settlement check's limit is set to 25% for this business.

## The planted stories

Each is unmistakable on purpose, and each is asserted by the script after it runs the Intelligence tasks. "Today" means the day
you run it; the history ends yesterday. The Tuesday of story 9 is simply *yesterday* (a Tuesday if you run it on a Wednesday,
which is what the check can see: it only judges the day before).

| # | What was planted | Finding it should cause |
|---|---|---|
| 1 | At Juja, **Brian Mwangi** (second cashier) works every day of the last 10 days and voids 8 of about 70 sales: 3 yesterday, 2 the day before. About five times the 1 to 2% of everyone else. | `pos.cashier_void_rate` (medium), "void rate was ...% over N sales" |
| 2 | One till closed **KES 8,400 short** (Ruiru, four days ago; Thika for the tiny scale). | `pos.till_cash_variance` (high); also `payments.close_variance` (the day's close carries the shortage) |
| 3 | The cement supplier's price rises about 18% over the last three deliveries (cost 600 until three deliveries before the end, then 1.02x, 1.07x and 1.19x). | `purchasing.supplier_price_rise` for Cement 50kg (and `purchasing.margin_squeeze`, since the selling price stays) |
| 4 | **Otieno Construction Co** (15 day terms) has an invoice from 85 days ago never paid (70 days overdue), then gets a new credit sale 3 days ago. | `pos.customer_overdue` (high) and `pos.credit_to_overdue_customer` (high) |
| 5 | **White emulsion paint 4L** runs out at Ruiru after selling steadily; no delivery planned. | `inventory.out_of_stock` |
| 6 | A **duplicate supplier bill**: Baraka Plumbing Wholesalers bills a haulage charge (21,500 + VAT) twice, two days apart, with different invoice numbers. | `purchasing.duplicate_supplier_bill` |
| 7 | A **manual write-off just above the limit** (about KES 1,060 against a limit of 1,000) by the storekeeper at **23:40** three days ago. Below the approval limit (5,000), so no approval. | `inventory.large_write_down` and `inventory.unusual_stock_moves` ("outside the usual hours") |
| 8 | **Collins Barasa** is added three days before last month's payroll run, and the payment details he gave are replaced the same day; he is paid in the run and has no attendance. | `people.changes_before_payroll` (high), `people.paid_without_attendance` |
| 9 | **Thika sells nothing yesterday** (a normal day there is about KES 40,000); the other branches trade as usual. | `pos.branch_sales_low` |
| 10 | **Fuel at Thika** costs KES 16,500 two days ago, against about 900 on a normal fuel day. | `finance.unusual_expense` |

Other findings you will see are real consequences of the data, not planted: low stock and out-of-stock, overdue customers
(the ageing), overdue supplier bills, an unmatched M-Pesa payment that was never rung up, payments with no provider
evidence, the Monday daily closes that were skipped (settlement day), the open bank reconciliation, overdue lead
follow-ups, leave waiting, a credit increase waiting for approval, and the stock count with differences.

Scales: `tiny` (only for the test suite: one branch, 20 sales, 14 days, stories 2, 6 and 7), `small` (45 days; stories 1 and 4
need 90 days of history, so they are left out; story 3 is checked only if there were at least four cement deliveries),
`full` (all ten).

After a full run the Findings screen has about 55 open findings in about 27 checks, the exceptions inbox about 40 open items
(old small till differences and payments waiting for the provider were cleared; recent and large ones stay), and the
Command Center shows today's tills open, the overdue customers (about KES 700,000), what is owed to suppliers and the
overdue supplier bills.

## Start over

```bash
.venv/bin/python scripts/seed_demo_rich.py --reset --confirm demo-hardware
```

drops the whole `demo-hardware` database and login and creates it again (owner `owner@demo-hardware.test`,
password `demo-pass-123`, company Demo Hardware Ltd in KES with branch Thika, time zone `Africa/Nairobi`, the catalog_stats
plugin on), writes the new id to `.demo_tenant` (which `scripts/seed_demo.py` reads) and then fills it. The old five-product
demo is not kept: its products are in the new list (`CEM-50KG`, `ROOF-G30`, `NAIL-4IN`, `PAINT-W4L`, plus `DELIVERY`). To make
the old small demo instead, drop the business the same way and run `bash scripts/run_local.sh`.

## Tests and upkeep

`tests/test_seed_demo_rich.py` seeds a scratch business `demo-seedtest` at the `tiny` scale (about 30 seconds), checks that
`ziira verify` and the trial balance are clean, that stories 2, 6 and 7 fire, that a second run changes nothing, and that
the immutability triggers are back on. When a service changes, the script is the first thing to tell you: run it.
