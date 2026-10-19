# Services wave 1: timebilling + shared invoice function (paused)

## Done and tested
- `pos.public.issue_invoice_from_lines`, `invoice_for_source`, `InvoiceLineIn`, `InvoiceRef` (idempotent by source; tax from the
  product; tax-inclusive `unit_price`; quantity/price validation; caller needs `invoices.manage`). Tests: `tests/test_pos_invoice_from_lines.py`
  (4 pass, with hand totals, idempotency, rollback on credit limit, permission); `tests/test_credit_sales.py` still passes (17).
- `ziira/modules/timebilling` backend: domain (rates precedence, timesheet rounding/weeks, billing lines, retainers, budgets) with
  unit + Hypothesis tests (`ziira/modules/timebilling/tests/test_domain.py`, 36 pass); services, API, events, hooks, pulse, 6 Intelligence
  checks, privacy provider, integrity check, manifest, plain-text catalogue entries (en/sw) in `intel/domain/plain_checks.json`.
- API/integration tests `tests/test_timebilling.py`: last run 29 pass (incl. `tests/test_architecture.py`), 1 fail (see below).

## Built, not fully verified
- `test_unsent_and_unapproved_timesheets_are_flagged` fails at its first assertion (check `timesheets_not_submitted` found nothing for
  user `boss`, week `monday(4)`); likely the test data/`unsubmitted_weeks` condition (week must have ended more than `grace_days` ago and draft
  entries dated before the cut-off), not yet debugged. The `approval_waiting` half is untested.
- Frontend `frontend/src/modules/timebilling/`: DONE and registered in `modules/index.ts` (see "Frontend state" below).
- `ruff`/`mypy` were clean for the backend files before the last test edits; `tests/test_timebilling.py` not linted.

## Remaining (in order)
1. Debug the failing test above. 2. Lint tests (ruff/mypy). 3. (frontend done, see below)
4. `docs/timebilling.md` (not written). 5. Custom fields (`timebilling.project`) once the framework's extension point exists.
6. Fuzzer hints in `tests/test_robustness.py` (not added; do not run the fuzzer blind). 7. `expire_due` retainers periodic task (function exists, no `@periodic` yet).
8. Re-run `scripts/export_openapi.py` + `npm --prefix frontend run api` after any schema change (types already generated once).

## Public surface
- pos.public: `issue_invoice_from_lines(session, *, company_id, branch_id, customer_id, lines, source_type, source_id, due_days=None, memo=None, issue_date=None) -> InvoiceRef`, `invoice_for_source`, `InvoiceLineIn(product_id, description, quantity, unit_price, discount=0, income_account_hint=None)`, `InvoiceRef`.
- timebilling.public: `unbilled_value(session, client_id)`.
- Events published: `timesheet.approved`, `timesheet.rejected`, `timebilling.invoiced`. Subscribed: `approval.decided` (doc type `timesheet`), `invoice.cancelled`.
- Extension points implemented: `intel.check` x6, `command.pulse_source`, `kernel.personal_data`, `kernel.integrity_check`.
- Permissions: time.log, time.view, time.approve, time.bill, projects.manage, rates.manage, time.cost, time.settings.

## Files and migrations
- `ziira/modules/pos/migrations/0010_invoice_source.{up,down}.sql` (source_type/source_id + partial unique index, line `description`); edited `pos/repository/models.py`, `pos/services/invoices.py` (line `description`), `pos/public.py`.
- `ziira/modules/timebilling/` (migration `0001_init`), `tests/test_timebilling.py`, `tests/test_pos_invoice_from_lines.py`.
- Shared files touched: `ziira/modules/intel/domain/plain_checks.json` (added entries/params/figures), `frontend/src/api/schema.d.ts` (regenerated).
- Note: a company-level permission check needs a company-wide role; branch-scoped managers cannot edit client billing settings, rates, settings.

## Resume
`set -a; . ./.env; set +a; caffeinate -dimsu .venv/bin/pytest tests/test_timebilling.py tests/test_pos_invoice_from_lines.py tests/test_architecture.py -q -p no:logging --tb=short`
and `.venv/bin/pytest ziira/modules/timebilling/tests -q -p no:cacheprovider`; then `.venv/bin/ruff check ziira/modules/timebilling tests/test_timebilling.py`, `.venv/bin/mypy ziira`, `.venv/bin/lint-imports`.

## Frontend state (final)
`frontend/src/modules/timebilling/`: 10 pages (My week with timer and week grid, Approvals, Team time (utilisation, `/time/overview`), Projects, Project detail with
Overview/Time/Stages/Retainer tabs, Clients, Unbilled work with the invoice reviews list, Invoice review, Rate cards with staff titles and the "What rate would this
get?" checker, Time settings), a `dashboard.widgets` card, English and Swahili (about 520 keys, parity tested), `lib.ts` (parsing and formatting of hours, week grid,
timer clock) with 35 tests. tsc, eslint, vitest (`modules.test.ts`, `pageTitles.test.ts`, key parity) clean for the module.
Smoke-tested with headless Playwright against the running app (demo-hardware, 1440 and 390 wide, no console errors): grid cells save (1.5 and 2:00 snapped to the 15 minute step),
timer start/pause/resume/stop, submit week, approvals page shows the own-week notice, approval turned off then week auto-approved, unbilled work, start review (asks the branch when
the business has several), edit a line, issue invoice (INV number, link via `invoiceHref`). Not exercised in a browser: reject/approve by a second person, retainer tab, milestones tab,
rate and staff editing, expenses dialog, forgotten-timer dialog, Swahili view.
Web-side choices: timer stop over 12 hours offers to type the real time; grid cells are totals per project/task/day (timer and quick-log time is edited in the "Logged one by one" list);
future days are disabled (backend refuses them); service items are filtered to type "service" in the browser (products list has no type filter, first 100 matches only).
Backend gaps found: `LineUpdateIn.minutes` is capped at 1440 so grouped time lines over 24 hours cannot have hours changed; custom fields skipped (`timebilling.project` is not registered as a
`kernel.custom_field_entity`); review `problems` are English-only server strings; `ReviewCreateIn.branch_id` is required for company-wide projects in multi-branch businesses (the web asks);
the generated schema names `EntryOut`, `ExpenseOut`, `SettingsOut` collide with other modules (types.ts resolves the prefixed or renamed name either way).
