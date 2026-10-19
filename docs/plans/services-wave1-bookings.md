# Services wave 1: bookings (paused)

Status when paused: the whole package is built and registered; the tree stays green for my files (ruff, mypy, import-linter,
architecture test, eslint, tsc, vitest pass for `bookings`). The backend API tests had not finished their last full run.

## Done and tested
- Domain (`ziira/modules/bookings/domain`): availability engine, lifecycle, recurrence, rules. `ziira/modules/bookings/tests/test_domain.py`: 20 tests incl. Hypothesis properties (all pass).
- Frontend: `lib.test.ts`, `booking-page/dates.test.ts`, `booking-page/PublicBookingPage.test.tsx`, `i18n.test.ts` (17 pass). eslint and tsc clean for the module.
- `tests/test_bookings.py` first run: 12 of 19 passed; the 7 failures were test mistakes (error body is `message`, instants are UTC, a series date clash, invoices need POS `invoices.manage`) and were fixed afterwards but NOT re-run to a clean pass.

## Built but not yet confirmed by a clean run
- `tests/test_bookings.py` (fixed), `tests/test_bookings_online.py` (public page, settings, messages, reminders), `tests/test_bookings_intel.py` (six checks, pulse, privacy, integrity, products/crm public functions). A combined run was in progress at pause (log: scratchpad `bk2.log`). Expect small test-side fixes.
- Messaging: five templates added to `ziira/kernel/message_templates.json`.
- Untested live: drag-to-reschedule and the calendar grid in a browser (no visual check done); QR/embed panel.

## Remaining, in order
1. Run the three test files to green and fix.
2. `tests/test_intel_plain.py` + `tests/test_templates*` (templates JSON) + `tests/test_editions.py` once the framework agent finishes.
3. Visual check of the calendar, front desk and `/book/<slug>` in a browser (scratch tenant, other port).
4. Edition `services` / pack seeding via `kernel.industry_seeder` (not implemented here).
5. Cut from v1: deposits, client self-service links, per-client quiet hours, class booking online, invoices per class attendee, baseline metrics.

## Defined for others
- Public: `bookings.public.find_appointment`, `customer_appointments`; additive `products.public.service_items`; additive `crm.public.match_or_create_customer`.
- SDK (additive): `claim_booking_slug`, `release_booking_slug`, `resolve_booking_slug`, `rate_limit`, `company_zone`.
- Events: `appointment.created|confirmed|rescheduled|cancelled|no_show|checked_in|completed|invoiced`. Extension points implemented: `intel.check` (6), `command.pulse_source`, `kernel.personal_data`, `kernel.integrity_check`.
- Web: `Calendar`, `Legend`, `bookingPageUrl` exported from `frontend/src/modules/bookings/public.ts`.
- The public API lives under `/api/v1/bookings/public/book/{slug}` (module prefix), not `/api/v1/public`.

## Files and migrations
- `ziira/modules/bookings/**` (migration `0001_init`), master migration `ziira/kernel/master_migrations/0018_booking_slug.up.sql`, `ziira/kernel/public_slugs.py`.
- Frontend `frontend/src/modules/bookings/**`; tests `tests/test_bookings*.py`, `tests/bookings_helpers.py`; docs `docs/bookings.md`.

## Shared files touched (all additive)
`ziira/sdk/__init__.py`, `ziira/kernel/message_templates.json`, `ziira/modules/products/public.py`, `ziira/modules/crm/public.py`, `ziira/modules/intel/domain/plain_checks.json`, `tests/test_robustness.py` (enable bookings + 4 body hints), `frontend/src/modules/index.ts`, `frontend/src/shell/App.tsx` (route `/book/:slug`), `frontend/src/api/schema.d.ts` (regenerated; regenerate again last), `CLAUDE.md` (one convention line). Note: the schema generator now qualifies duplicate names (timebilling `SettingsOut` etc.), which breaks `Schemas["SeriesOut"]`, `EventOut`, `ExpenseOut` and others elsewhere until those schemas are renamed.

## Resume commands
```
cd /Users/mac/projects/ziira-core && set -a; . ./.env; set +a
caffeinate -dimsu .venv/bin/pytest tests/test_bookings.py tests/test_bookings_online.py tests/test_bookings_intel.py ziira/modules/bookings tests/test_architecture.py tests/test_intel_plain.py -q
.venv/bin/ruff check ziira/modules/bookings tests/test_bookings*.py; .venv/bin/mypy ziira; .venv/bin/lint-imports
make api-types; cd frontend && npx tsc -b --noEmit && npx eslint src/modules/bookings && npx vitest run src/modules/bookings
```
