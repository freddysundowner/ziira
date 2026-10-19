# Services wave 1: memberships package (paused)

State when paused: backend and web module complete in code, lint/mypy/import-linter/tsc/eslint/vitest clean for the module.
Nothing committed.

## Done and tested (passing)
* Domain rules (`ziira/modules/memberships/tests/`: periods, proration, credit allocation, quiet hours; Hypothesis): 17 pass.
* `tests/test_memberships.py` (26 tests, real sign-ins, real invoice service): plans/permissions, sign-up + invoice, price snapshot, renewals exactly once,
  catch-up/skip + flags, failed renewal retried once, proration, pause/resume, cancel (reason, period end/now), fixed term, credits (idempotent consume,
  release, overdraw, adjust), packages (sell, expire, refund), recurring invoices (exactly once, run limit, draft/issue/discard, pause, failure + retry). All passed.
* Architecture test, `tests/test_intel_plain.py`, manifest description test pass.
* Frontend: tsc, eslint, vitest (8 tests) clean for `frontend/src/modules/memberships`.

## Built but not confirmed
* `tests/test_memberships_more.py` (events, reminders, personal data, custom fields, concurrency, integrity check, failure isolation, branch scope,
  plan without service item) and `tests/test_memberships_intel.py` (4 checks + pulse, real engine): written; first run of "more" had 7 test-side errors, fixed
  (helper `phone` kwarg, custom-fields route `/entities`, package dates); re-run was in progress (`scratchpad/mem_run3.txt`) and unconfirmed.
* Web screens never viewed in a browser.
* `make site-catalog` not run: `tests/test_check_catalog.py` fails today because bookings checks have no entry in `site/src/content/checks.plain.json`
  (not mine); my four checks have entries there and in `plain_checks.json`. Regenerate `checks.catalog.json` once all packages added theirs.

## Remaining (in order)
1. Re-run the two test files above and fix what fails.
2. Run `tests/test_robustness.py` (fuzzer; I added the memberships shop objects and valid bodies, not run).
3. Look at the screens in the browser (Services area); add member search if wanted (needs a Customers search function).
4. `make site-catalog`; add docs/memberships.md to CLAUDE.md "Where things are".

## Public surface
* `memberships/public.py`: `member_credit_balance`, `consume_credit` (returns `CreditUse`), `release_credit`, `active_membership`, `member_discount_percent`.
* Events: `membership.activated|renewed|paused|resumed|cancelled|expired`, `package.sold|used|expiring|expired`.
* Implements: `intel.check` (4), `command.pulse_source`, `kernel.personal_data`, `kernel.integrity_check`, `kernel.custom_field_entity` (`memberships.member`).
* Periodic tasks `memberships.run_billing`, `memberships.send_reminders`. Reason category `membership_cancel`. Templates `membership_renewal`, `package_expiring`.

## Files and migrations
* `ziira/modules/memberships/` (manifest, migration `0001_init` only, domain, services, repository, api, hooks, jobs, intel_checks, pulse, privacy, public, README, tests).
* `docs/memberships.md`, `tests/test_memberships*.py`, `tests/memberships_helpers.py`, `frontend/src/modules/memberships/` (module, 4 pages, components, slot on the customer page, i18n en/sw).

## Shared files touched (additive)
`ziira/kernel/message_templates.json` (2 templates), `ziira/modules/intel/domain/plain_checks.json` and `site/src/content/checks.plain.json` (4 checks, labels),
`tests/test_robustness.py` (enable unit, objects, bodies), `tests/test_channels_rules.py` (template set check made a subset check),
`frontend/src/modules/index.ts` (import + list), `frontend/src/api/schema.d.ts` (regenerated).

## Resume
```
set -a; . ./.env; set +a
.venv/bin/pytest ziira/modules/memberships/tests -q
caffeinate -dimsu .venv/bin/pytest tests/test_memberships.py tests/test_memberships_more.py tests/test_memberships_intel.py tests/test_architecture.py -q
.venv/bin/ruff check ziira/modules/memberships tests/test_memberships*.py tests/memberships_helpers.py; .venv/bin/mypy ziira; .venv/bin/lint-imports
cd frontend && npx tsc -b --noEmit && npx eslint src/modules/memberships && npx vitest run src/modules/memberships
```
