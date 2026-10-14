# Performance

How fast Ziira Core is on a realistic multi-branch business, how to measure it again, and what to watch in production.
Written for phase 11 (hardening). Numbers are from one machine and one run; treat them as a baseline to compare against,
not as a promise.

**Machine:** a MacBook Pro (Intel i9, 16 threads, 64 GB), PostgreSQL 16.13 in Docker Desktop (7.6 GB, default
settings: `shared_buffers` 128 MB, `work_mem` 4 MB, so the data does not fit in cache), the API run with `uvicorn`
on the same Mac, client and server competing for the same CPUs. Every database statement crosses Docker's network
layer (about 1 ms each), which is slower than a database on the same VPS; a sale makes about 150 statements, so
**absolute latencies here are pessimistic**. Re-measure on the real server before setting alerts.

## The seeded business

`scripts/seed_load.py --preset full` (about 15 minutes): 3 branches, 6 tills, **5,000 products, 20,000 customers
(2,000 with credit), 150,000 POS sales** with 330,000 lines and payments over 12 months, 11,800 credit invoices and
7,000 receipts, 8,000 supplier bills with receipts and payments, **365,000 stock movements**, 100 employees and 12
payroll runs (calculated, approved, paid), **536,000 journal entries / 1.24 million journal lines**, 21,000
Intelligence findings. About 1.5 GB. `ziira verify` is clean on it (stock ledger, books, customer ledger).

## Results (before and after)

Flat-out requests (no pauses). `sale_post` is 20 tills posting at once; the others are 8 (lists) or 4 (reports)
parallel clients. One API process. Times in ms.

| Path | Before p50 / p95 | After p50 / p95 | Notes |
|---|---|---|---|
| POS sale post, 1 till alone | 350 / - | 106 / 160 | 3-line cash sale |
| POS sale post, 20 tills flat out | 6,180 / 10,100 (2.8 sales/s) | 1,400 / 2,400 (12.7 sales/s) | queue on journal numbering, see below |
| POS sale post, 20 tills, a sale per till every ~5 s | not measured | 133 / 228 (3.6 sales/s) | realistic busy shop |
| Sale retry (same `local_id`) | - | 17-30 alone | returns the first result, writes nothing |
| Product list / search | 135 / 261, 118 / 185 | 63 / 99, 56 / 94 | |
| Stock balances | 129 / 230 | 70 / 138 | |
| Customer search (20,000) | 148 / 208 | 88 / 121 | sequential scan, see "Not done" |
| Stock movements list (newest first / filtered) | **495 / 1,378** | 58 / 98 | index on `created_at` |
| Supplier bills list | 155 / 254 | 68 / 114 | |
| Sales list | **433 / 912** | 81 / 254 | index on `sold_at` |
| Receivables ageing | **1,890 / 2,372** | 978 / 1,045 (295 alone) | still reads open invoices into Python |
| Trial balance, a whole year | **5,650 / 6,080** | 1,350 / 1,410 | |
| Profit and loss, a year | **6,030 / 6,480** | 1,420 / 1,490 | |
| Balance sheet | **5,070 / 5,130** | 1,380 / 1,510 | |
| Command overview | 37 / **13,940** (first look of the day) | 119 / 171 | first look recomputes the figures (about 0.5 s alone) |
| Findings list / summary | 78 / 139 | 80 / 113 | |
| Payroll calculate (100 employees) | 2,550 | 1,510 | |
| **Intelligence `run` for the company** | **227,000** (3.8 min) | **10,600** | 68 checks take 3.3 s of it; the rest is writing 21,000 findings |
| All 68 checks (read only, in process) | 13.1 s | 3.3 s | `scripts/loadtest.py --checks-profile` |

The reports share one CPU with the load generator here; with 4 clients on one process each report takes about a
quarter of the number shown when it runs alone (a trial balance runs in about 150 ms in the database).

## What was wrong and what changed

Found with `EXPLAIN (ANALYZE, BUFFERS)`, `cProfile` of a sale, `log_min_duration_statement = 0` on the scratch
database and `pg_locks`.

1. **Every posting took a company-wide lock** (`finance/services/books.py: ensure_books`) and ran about 60 queries
   (one per chart account) to find nothing to add. Now two cheap reads, no lock when the books are complete, and the
   answer is remembered for the transaction. This alone halved the cost of a sale (350 -> 160 ms).
2. **The audit chain locked the tenant from the first audited call to the commit** (`kernel/audit.py`): every write
   of the business queued behind the one before. Entries are now queued and written, chained, just before commit
   (same order, same hashes, none on rollback). `audit.flush_pending(session)` writes them early for code that has to
   read the log inside its own transaction.
3. **Repeated lookups per transaction** (`check_company`, company settings, enabled units, POS unit checks) are asked
   once and remembered for the transaction (sale: 350 -> 106 ms with 1 and 3).
4. **Document numbering took two locks** (an advisory lock, then the row); the first is now only for creating a series
   (`kernel/numbering.py`).
5. **Intelligence wrote findings one at a time** (a read, an insert, an event insert, an outbox insert each). Now one
   read per check and bulk writes (`intel/services/engine.py`, `kernel/events.py: publish_many`); behaviour is
   identical. `crm.over_credit_limit` asked for each customer's balance separately; `pos.public.customer_balances`
   does it in two queries.
6. **Indexes** (new numbered migrations, each says that migrations run in a transaction, so plain `create index`,
   which blocks writes while it builds; run upgrades of a large business in a quiet period):

   | Migration | Adds | Helps |
   |---|---|---|
   | `finance/0007_line_entry_date` | `journal_line.entry_date` (copy of the entry's date, filled by a trigger; one-time backfill lifts the immutability guard while it runs), `journal_line_ix4`, `journal_line_ix5` | every report: no join of 1.2 million lines to 536,000 entries |
   | `inventory/0004` | `stock_movement_ix4..ix7` (`created_at`, per location, per product, by date and type) | movement list, checks |
   | `pos/0006` | `sale_ix4..ix6`, `sale_payment_ix1`, `sale_line_ix1`, `customer_receipt_allocation_ix2` | sales list, customer history, payments of a sale |
   | `payments/0004` | `payment_allocation_ix2`, `payment_ix4`, `payment_ix5` | allocations, close |
   | `purchasing/0007` | bill/receipt line and bill status indexes | three-way match, purchasing checks (`paid_without_receipt` 3.6 s -> 0.1 s) |
   | `people/0003` | `payslip_line_ix1` | payslips |

   `tests/test_performance_indexes.py` fails if one of these disappears, and checks on 20,000 movements and
   journal lines that the newest-first movement list and a month of ledger lines read an index.

## Targets

| Path | Target | Now (this Mac) |
|---|---|---|
| Sale post, p95, 20 tills each selling every 5 s | < 150 ms | 228 ms (about 60% of it is Docker round trips; re-measure on the server) |
| Sale post, single till | p95 < 150 ms | 160 ms |
| Product search / list, p95 | < 100 ms | 94-99 ms |
| Reports for a year (trial balance, P&L, balance sheet), p95 | < 2 s | about 1.5 s under load, 0.15-0.35 s alone |
| Receivables ageing | < 1 s | 1.0 s under load |
| Intelligence run per company | < 60 s | 10.6 s (first run with 21,000 findings) |
| `ziira verify` | < 5 min | 34 s |

## Known limits (not fixed, decisions needed)

* **Journal numbers serialise sales.** A sale takes the next number of the company-wide SAL and STK journal series and
  keeps the row lock until it commits (that is how the numbering stays free of gaps). Flat out, the company tops out at
  about 13 sales/second whatever the number of API processes; at one sale per till every 5 s with 20 tills (4/s) it is
  invisible. A business that outgrows this needs per-branch journal series (changes the number format) or numbering
  assigned at commit. Hot products also serialise on their cost row for the length of a sale.
* **Customer and product search** use `ilike '%text%'` (sequential scan: 50 ms for 20,000 customers, 12 ms for 5,000
  products). Past about 100,000 rows add a `pg_trgm` index (`create extension pg_trgm` needs database privilege;
  not added here).
* **Receivables ageing** loads every open invoice into Python (295 ms for 4,800). Summing in SQL is the next step.
* **`ziira verify` / `stock-verify`** read every stock movement into memory (`inventory_repo.movement_history`);
  fine at 365,000, plan streaming for millions.
* **Database pool**: 2 + 8 connections per tenant per API process (`ZIIRA_DB_POOL_SIZE`, `ZIIRA_DB_MAX_OVERFLOW`).
  20 tills on one process share 10 connections.
* **First look of the day** on the Command Center recomputes the figures inside the request (about 0.5 s; several
  people arriving together wait for each other). The worker refreshes them hourly.
* The bulk seed writes no audit-log or outbox rows, so those tables are smaller than a year of real use.

## How to measure again

```bash
.venv/bin/python scripts/seed_load.py                    # small preset (about a minute); --preset full for the table above
.venv/bin/python scripts/loadtest.py --spawn             # own API on :8765, every scenario, 20 tills
.venv/bin/python scripts/loadtest.py --spawn --workers 2 --only sale_post --think-ms 5000 --json out.json
.venv/bin/python scripts/loadtest.py --checks-profile    # time each of the ~70 Intelligence checks
.venv/bin/ziira drop-tenant <perf-code> --confirm <perf-code>
```

`seed_load.py` only creates tenants whose code starts with `perf-`. `loadtest.py` refuses any other workspace.
For plans: `docker exec -i ziira-core-db-1 psql -U ziira -d ziira_t_<code> ` and `explain (analyze, buffers)`;
`alter database ziira_t_<code> set log_min_duration_statement = 50` logs slow statements for one database.
`vacuum (analyze, parallel 0)` after a bulk load (Docker's 64 MB shared memory is too small for parallel vacuum).

## What to watch in production

* **Slow query log:** `log_min_duration_statement = 250` (ms) on the server, reviewed weekly; enable `auto_explain`
  with `auto_explain.log_min_duration = 1000` for plans.
* **`pg_stat_statements`** (add to `shared_preload_libraries`, `create extension` per database): top statements by
  total time and by calls (a high call count with low time is a new N+1 pattern; a sale should stay near 150 statements).
* **Connections:** `select count(*), state from pg_stat_activity group by state`; API processes x tenants x (pool + overflow)
  must stay under `max_connections`, or put PgBouncer in front (`ZIIRA_PGBOUNCER=true`). Alert when `idle in
  transaction` lasts more than a few seconds.
* **Locks:** `select * from pg_stat_activity where wait_event_type = 'Lock'`; many waiters on `document_series` rows
  means the numbering limit above has been reached.
* **Table and index growth:** `pg_stat_user_tables` / `pg_total_relation_size` for `journal_line`, `stock_movement`,
  `sale_line`, `kernel.audit_log`, `kernel.event_outbox` (purge published outbox rows), and `n_dead_tup` (autovacuum
  keeping up; the `journal_line_ix4` backfill leaves dead space until the next vacuum).
* **Server settings** to review for real data volumes: `shared_buffers` (about 25% of RAM), `effective_cache_size`,
  `work_mem`, `max_connections`.
* The access log (`ziira.access`, one line per request with `duration_ms` and route) gives per-route p95 without any extra tool.
