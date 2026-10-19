# Services wave 2, agent A: bookings, pack_salon, pack_clinic

Status: DONE for this wave (see Remaining). Owner of: `ziira/modules/bookings`, `frontend/src/modules/bookings`,
`ziira/plugins/pack_salon`, `ziira/plugins/pack_clinic`. Do not commit; do not push.

## Audit at the start (what wave 1 had vs the brief)
Had: resources with weekly hours and time off, service offers, appointments (exclusion constraint), waitlist for appointments,
series, simple class (capacity + attendee list), calendar, front desk list, reminders, public booking page, one-line invoice, Intelligence
checks. Gaps against the brief: no checkout (cashier could not invoice: Point of Sale's `invoices.manage`), no retail/tips/discount/
deposit/credit/split payment, no processing time, no price by staff level, no visits of several services, no "who is free" board or
walk-in queue, no class waitlist/auto-promotion/late-cancel, no closed days, no recalls, no no-show/late-cancel fee, no commission, no
chair rental, no day-end, no client card/patch-test warning, no insurer/co-pay seam, no photos/documents, no industry seeding or packs.

## Done (tested)
* Migration `0002_wave2`. Domain `domain/checkout.py` (hand-calculated + Hypothesis tests), processing time in the availability engine.
* Checkout (`services/checkout.py`, `/checkouts`): draft, member discount, package/membership credit, discount with reason + manager limit,
  fees, deposit applied, split payments, tips, commission, payer/co-pay split into two invoices, all-or-nothing, idempotent.
  The front desk may bill through `bookings.checkout` (lent POS rights only inside the call; `services/delegate.py`).
* Group sessions (`services/sessions.py`, `public.py`): capacity race-safe, auto-promoting waitlist with confirm window, late cancel,
  attendance, closed days, capacity change, instructor swap, cancel session; events documented in `docs/bookings.md`.
* Front desk: board, smart walk-in/queue, visits in sequence, price variants by level, rota, recalls + rebook prompts (worker), fees,
  commission rules/report/figure, tips owed/pay-out, chair rental (worker), day-end, client card, patch-test warning.
* Tests: `tests/test_bookings*.py`, `ziira/modules/bookings/tests/`.

## Added to other units (additive, tell the owners)
* `pos/public.py`: `issue_invoice_from_lines(..., location_id=, settled_now=)`, `take_payment`, `customer_credit`,
  `apply_account_credit`, `settle_invoice_non_cash`; `pos/services/invoices.py`: `issue_invoice(settled_now=)`.
* `kernel/message_templates.json`: class_booked, class_place_offered, class_cancelled, appointment_recall(_clinic),
  appointment_rebook(_clinic), appointment_reminder_clinic, appointment_deposit.
* `docs/memberships.md` ("Paying at the front desk"). NOTE: pos/public.py now has duplicate definitions from other agents
  (`InvoiceState`, `CreditRef`, `invoice_states`): the lead should dedupe.

## Also done
* Packs `pack_salon` and `pack_clinic` (data, seeder in `services/seed_industry.py`, first-run steps, sample week, docs `docs/pack_salon.md`,
  `docs/pack_clinic.md`); web screens: Front desk board + walk-in strip, Checkout, Bills, Classes (+ closed days), Due again, Staff pay (commission,
  tips, rules, rent), Day end, Rota, client card, deposit/insurer dialogs, settings/offer/resource additions; English and Swahili.
* Intelligence: `bookings.tips_held`, `bookings.deposits_unpaid`; plain text added (plain_checks.json, site catalog regenerated).
* Browser walk (own tab, 1440 and 390): salon walk-in -> start -> checkout -> paid bill; public booking page with a deposit request. The clinic
  path was verified by API tests only (not walked in the browser).

## Remaining / doubts
* Claims seam: Claims may also invoice the patient's excess; needs agreement with agent F (see docs/pack_clinic.md).
* Memberships owner: implement `CheckoutTender` for vouchers/points (documented in docs/memberships.md); no voucher exists yet.
* `pos/public.py` has duplicate definitions from other agents (`InvoiceState`, `CreditRef`, `invoice_states`, `ReceiptRef`): the lead should dedupe.
* Deposits have no online payment link; no confirm link for a freed class place; tips are not posted to the books; rule edits cannot clear a rule's person.
* Existing businesses that already enabled bookings do not get the new Cashier permission `bookings.checkout` automatically (roles are seeded at enable).

## Resume commands
```
cd /Users/mac/projects/ziira-core && set -a; . ./.env; set +a
.venv/bin/pytest tests/test_bookings*.py ziira/modules/bookings tests/test_architecture.py tests/test_intel_plain.py tests/test_openapi_names.py -q -p no:logging
.venv/bin/ruff check ziira/modules/bookings; .venv/bin/mypy ziira/modules/bookings; .venv/bin/lint-imports
make api-types; cd frontend && npx tsc -b --noEmit && npx eslint src/modules/bookings && npx vitest run src/modules/bookings
```
