# Wave 2, agent B: Jobs and the garage pack

Status: stopped on the owner's instruction. Nothing committed. Everything below was run unless marked "not run".

## Audit (what wave 1 lacked)
Odometer/intake details, item history on intake, next-service reminders, invoicing a walk-in, additional-work estimates and unapproved-work rule,
work types and task library, booked vs billed hours, part class/category markup, ordered and customer parts, unused returns, charges (towing,
storage), deposit, release-on-payment rule, bays, courtesy cars, photos, insurer link, technician views, pack data, sample data. All of it now exists
(see docs/jobs.md "Workshop features" and docs/pack_garage.md).

## Done
- Migrations 0002 (garage), 0003 (photos), 0004 (pack steps, sample data). They were never applied outside throwaway test databases and one local dev DB.
- Backend: services catalog, approval, charges, deposit, release, bays, loans, reports, service_due, photos, claims_link, seed_industry, pack_steps,
  sample_data; routes and schemas; events (goods.received, claim.*); periodic reminders (service due, pickup); checks `jobs.part_overdue`,
  `jobs.courtesy_car_overdue`; messages job_extra_work/job_service_due/job_pickup_reminder; plain text for the checks.
- Pack `ziira/plugins/pack_garage` (data only) with docs/pack_garage.md.
- Web: intake fields and item history, parts/labour/charges dialogs, estimates (additional work), alerts, photos tab (Attachments), workshop tab,
  claim card, invoice (pay now) and collect (unpaid confirm) dialogs, Workshop page (my jobs, bays, technicians, service due, cars out), settings
  tabs (getting started, kinds of job, labour and parts, bays, rules), public approval (photos, class). English and Swahili parity tests pass.
- Tests: tests/test_jobs.py (one test updated for walk-in invoicing), test_jobs_garage.py, test_jobs_insurer.py, test_jobs_photos.py,
  test_jobs_intel.py (+1), test_pack_garage.py: 89 passed together with test_architecture and test_intel_plain. ruff, mypy (jobs), lint-imports,
  tsc, eslint, vitest (jobs) clean. Not run: fuzzer, full suite, e2e, Hypothesis for the new pure rules.

## Real-browser walk (own tab, own stack on ports 8010/5174, database ziira_b_master, tenant mama-garage)
Done by hand: private job (intake, task labour, stock part with category markup, estimate, customer approval on the link with a shareable photo,
additional work found: banner, additional estimate, recorded by staff, collect with the unpaid warning, invoice paid now, collect, hand-over);
insurer job (walk-in, claim opened, payer-rate pricing, insurer estimate drafted from the job, insurer answered on the response link: approve,
reject, counter, authority number; the job moved to Approved and showed go-ahead/hold lines).
Not walked: counter acceptance, customer's decision on the rejected line, sign-off, invoice split and excess collection in the browser (covered by
test_jobs_insurer.py); tailoring order; bay board, courtesy car, deposit and the technician screens in the browser; Swahili screens; phone width.
Bugs found and fixed in the walk: warning shown while the first estimate was still with the customer; locked job could not save next service;
walk-in job could not open an insurer claim (added `POST /jobs/{id}/customer-record` and a prompt); duplicate payer messages.

## Half-done / known gaps
- The last two small edits (insurer alert wording, claim card message) compile but were not re-checked in the browser.
- Pack SKU linking: if the pack is applied before a unit of measure and tax code exist, the items link on the next `ziira apply-packs` (fixed in code, no test).
- No technician timers; deposit is not allocated to the invoice; storage after invoicing is not billed; no Hypothesis tests.
- Shared edits made outside my folders (additive): `pos/public.py` (invoice_balance), `crm/public.py` (walk_in_customer), `crm/hooks.py` + manifest
  (custom field entity `crm.customer`), `purchasing/public.py` (find_order_by_number), `claims/public.py` (payer_terms, draft_estimate, bill_claim,
  complete_claim_work, ensure_payer, retire_payer, close_claim_for_source), `kernel/message_templates.json` (3 templates),
  `intel/domain/plain_checks.json` (2 entries), `frontend/src/api/schema.d.ts` (regenerated).
- Seen, not mine: duplicate `InvoiceState`/`CreditRef` definitions in `pos/public.py` (mypy), duplicate schema names in test_openapi_names.

## Resume
```
set -a; . ./.env; set +a
.venv/bin/pytest tests/test_jobs.py tests/test_jobs_garage.py tests/test_jobs_insurer.py tests/test_jobs_photos.py tests/test_jobs_intel.py tests/test_pack_garage.py -q
.venv/bin/ruff check ziira/modules/jobs ziira/plugins/pack_garage; .venv/bin/mypy ziira/modules/jobs; .venv/bin/lint-imports
cd frontend && npx tsc -b && npx eslint src/modules/jobs && npx vitest run src/modules/jobs
make api-types   # last
```
Local walk stack: scripts in the session scratchpad (restart.sh builds the web app and serves it, since the dev server reloads when others edit).
