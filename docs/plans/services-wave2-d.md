# Wave 2, agent D: memberships and the fitness pack (gyms, studios, trainers)

Status: backend complete and tested; web screens built but NEVER seen in a browser; sign-in to the demo business was blocked by a login throttle on the dev machine at wrap-up, so the browser month walk was NOT done. Not committed.

## Audit of what existed (start of wave 2)
Memberships wave 1 had plans (month/quarter/year, credits, discount), members (snapshot of the plan, hold, cancel), sold packages,
the credits ledger, recurring invoices and the worker task, reminders, four Intelligence checks, personal-data provider. Gaps against
the brief, all closed or listed below:

| Brief item | Wave 1 | Now |
|---|---|---|
| profile, photo, member number, emergency contact | none | `memberships.profile` (number from kernel numbering "M-", card, emergency contact, birth date, source, referrer, tags, block); photo through the files service (`memberships.profile` attachable, `photo_file_id` must be a picture attached to the profile) |
| waiver/terms (who, when, version, no health data) | none | versioned `waiver_version` + immutable `waiver_acceptance` (typed name, method, recorded by) |
| household/corporate, one payer | none | `account_group`; members' invoices go to the payer (`billing_customer_id`), also for packages, freezes, rentals |
| trial | none | trial plans (pass + `is_trial`), profile lifecycle `trial`, follow-up message, conversion figure |
| plan types | month/quarter/year only | recurring, fixed-term (minimum term, notice, exit fee), pass (day/week/trial), off-peak windows, class-only, per-branch list, joining fee, freeze rules, guest passes, per-plan proration |
| upgrade/downgrade | none | quote, upgrade now with proration + extra credits, downgrade/other interval booked for next renewal |
| price changes from a date | none | `plan_price_change` (not retroactive; optional for existing members; price-lock) |
| billing that does not leak | invoices only | arrears per invoice/member, late-payment steps (queued, once each), grace days, hold for unpaid fees (auto-freeze/auto-resume), take payment with receipt, write-off/refund by credit note through Sales, dunning pause, late list, CSV |
| check-in | none | one decision engine for desk/scan/card/kiosk/API; override with reason (audited); offline queue+sync; roster; access-decision API + webhook event |
| vouchers, points, referral, lockers, guests | none | value ledger (`value_account`/`value_entry`), referral reward, points, lockers with recurring rent + deposit, guest passes |
| trainers | none | per-trainer rate (fixed/percent), earnings from `appointment.completed`, report, mark paid; measurements the member shares |
| reports | summary counts | owner overview (active, new/ended, MRR, by plan, retention cohorts, attendance heat map, arrears ageing, freezes, trials, leaving reasons, trainers, revenue at risk), CSV exports |

## Done (backend, tested)
Migrations `0002_members_billing_checkin`, `0003_extras_values_trainers`. Services: profiles, waivers, holds, changes, dues, checkin,
values, extras, trainers, retention, reports, seed_industry. Domain: `domain/access.py` (pure door rule, Hypothesis-tested).
Tests: `ziira/modules/memberships/tests/test_access.py`, `tests/test_gym_members.py`, `tests/test_gym_billing.py`, `tests/test_gym_checkin.py`
(check-in median well under 250 ms through the API with 4,000 members; roster of 4,000 under 6 s), plus the wave 1 tests still pass.

## Shared files I touched (additive)
`ziira/modules/crm/public.py` (`search_customers`, `LeadView`, `find_lead`, `capture_lead`, `make_customer_from_lead`),
`ziira/modules/pos/public.py` (`InvoiceCredit`, `credit_invoice`: credit note/refund by amount; I reuse agent F's `invoice_states` and agent A's
`take_payment`), `ziira/kernel/public_api.py` (two memberships endpoints), `ziira/kernel/message_templates.json` (5 templates),
`ziira/modules/intel/domain/plain_checks.json` and `site/src/content/checks.plain.json` (3 checks), CLAUDE.md "Where things are" later.

## Also done since the first draft
Classes: credits on `class.attendee_*` events (tests). Vouchers/credit/points at Bookings' checkout (`tender.py`, kinds voucher, credit, loyalty; tested by calling the providers). Member photos through the files service (tested end to end). `GET /setup-steps` first-run checklist. Fitness pack `ziira/plugins/pack_fitness` (data, 8 plans, 4 packs, policies, terms, fields; `tests/test_gym_pack.py`). Sample data `scripts/seed_demo_gym.py` (ran once: creates `demo-gym`, login owner@demo-gym.test / demo password; `ziira index-logins demo-gym` was needed). Docs: `docs/memberships.md` "Gyms and studios", `docs/pack_fitness.md`, public-api, webhooks, industry-packs, CLAUDE.md. API types regenerated. Web screens (by a sub-agent, tsc/eslint/vitest clean, 48 module tests): check-in desk with offline queue, kiosk, member page tabs, plans/packs/policies/terms, money owed, reports, extras, getting-started card; i18n en/sw (Swahili not reviewed by a native speaker).

## Gaps (honest)
* Web screens not viewed in a browser; nothing walked end to end (join, check in, freeze, renew, late payment, class waitlist, PT pack). Do this first: `ziira index-logins demo-gym`, clear `master.auth_throttle` if sign-in is locked, run API + vite, sign in as owner@demo-gym.test.
* Check-in does not show "classes booked today": Bookings has no public function for a customer's sessions (needs `bookings.public.customer_sessions_today`); `classes_today` is always empty.
* Trainer utilisation (needs availability from Bookings); instructor pay per class.
* Downgrade mid-period refunds nothing; part-paid credit by amount can leave a few cents. No card-on-file auto-charge. Hardware out of scope.
* Intelligence defaults from the pack (`apply_check_defaults`) are untested (intel not enabled in the pack test). Fuzzer, full suite and e2e not run. `tests/test_check_catalog.py` fails for reasons outside my files (other units' checks lack plain text; the catalogue JSON must be regenerated with `make site-catalog` by the lead).
* Kiosk waiver step and guest passes need the manage right; kiosk keypad has digits only.

## Resume
```
set -a; . ./.env; set +a
caffeinate -i .venv/bin/pytest tests/test_gym_pack.py tests/test_gym_extras.py tests/test_memberships.py tests/test_memberships_more.py tests/test_memberships_intel.py tests/test_gym_members.py tests/test_gym_billing.py tests/test_gym_checkin.py ziira/modules/memberships/tests -q
.venv/bin/ruff check ziira/modules/memberships tests/test_gym*.py; .venv/bin/mypy ziira/modules/memberships; .venv/bin/lint-imports
```
