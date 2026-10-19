# Services wave 1: Jobs and Repairs (paused)

Docs for the unit itself: `docs/jobs.md`. Paused on the owner's request; nothing committed.

## Final state (resumed and finished)
**Backend: done and green.** `tests/test_jobs.py` 28 passed, `tests/test_jobs_intel.py` 7 passed, domain tests 8 passed,
`tests/test_architecture.py` and `tests/test_intel_plain.py` 14 passed (each file run on its own). ruff, mypy and lint-imports are clean for jobs.
The fuzzer was not run (hints are in `tests/test_robustness.py`).

**Web module: done, registered.** `frontend/src/modules/jobs/`: board (drag and drop plus "Move to" menu) and list, receive form, job page
(overview, checklist, tasks, parts and labour, estimates, timeline, summary with custom fields), items list and item page, job settings
(stages and moves, checklists, rates and invoicing), dashboard widget, and the public approval page at `/job-approval/:token`
(`approval/`, plain fetch to `/api/v1/jobs/public/job-approval/{token}`, EN/SW switch, mobile first). i18n: 414 keys, identical in English
and Swahili. Registered in `modules/index.ts` and `shell/App.tsx` (route). Schema names follow `docs/plans/services-schema-renames.md`
(`JobEventOut`, `JobSettingsOut`, `JobTemplateOut`; all in `types.ts`). `tsc -b`, eslint (jobs, App.tsx) and vitest (jobs, sdk, modules,
pageTitles, i18n parity) pass, except `src/sdk/areas.test.ts` "keeps sections to about seven entries": the Services area now has 13
pages (limit 12 in that test) because four modules share it; not caused by Jobs alone. `src/modules/index.ts` also has an unused
`timebilling` import from another package that fails tsc/eslint.

**Checked in a real browser** (headless Playwright, demo business, `jobs` enabled with `ziira enable demo-hardware jobs`): board, list, job
(parts, labour, estimates tabs), intake, items, settings, home widget at 1440 and 390 wide, and the customer approval page at both widths
with a real approval at 390 (job moved to Approved, no console errors). Screenshots:
`/private/tmp/claude-501/-Users-mac-projects-ziira-core/a81d785c-404a-4225-b982-ee5ea7467415/scratchpad/jobs_shots/`. Not exercised by hand:
drag and drop, collect, invoice, return visit and the settings editors in the browser (covered by API tests only).

## Left for later
Pack data files (`data/jobs.toml` in `pack_garage` etc.); a nicer mobile board (empty columns could fold away); drag and drop and the settings
editors need a browser test; run the fuzzer once; optional "Items" as a tab under Jobs if the sidebar must shrink.

## Defined by this package
- Public functions: `jobs.public`: `seed_statuses`, `parse_definition`, `seed_checklist`, `find_job`, `add_labour_line`, `Definition`, `StatusDef`, `DEFAULT_WORKFLOW`.
  `inventory.public`: `issue_stock_to_job`, `return_stock_from_job` (+ `JobStockView`).
- Events: `job.received`, `job.status_changed`, `job.estimate_approved`, `job.estimate_declined`, `job.collected`, `job.invoiced`.
- Implements: `intel.check` (5), `command.pulse_source`, `kernel.personal_data`, `kernel.integrity_check`, `kernel.custom_field_entity` (`jobs.work_order`, `jobs.asset`), `kernel.industry_seeder` (data file `jobs.toml`).
- Permissions: `jobs.view/manage/parts/estimate/invoice/settings`.

## Files and migrations
- New: `ziira/modules/jobs/` (migration `0001_init` only), `ziira/modules/inventory/migrations/0005_job_stock`, `ziira/modules/inventory/services/job_stock.py`,
  `docs/jobs.md`, `tests/jobs_helpers.py`, `tests/test_jobs.py`, `tests/test_jobs_intel.py`, `frontend/src/modules/jobs/` (partial).
- Shared files touched (additive): `ziira/modules/inventory/{public.py,domain/movements.py}` (movement kinds `job_issue`, `job_return`),
  `ziira/modules/finance/domain/recipes.py` (cost of goods sold recipe), `ziira/kernel/message_templates.json` (`job_ready`, `job_estimate`),
  `ziira/modules/intel/domain/plain_checks.json`, `frontend/src/modules/inventory/i18n/{en,sw}.json`, `frontend/src/modules/pos/public.ts` (`invoiceHref`),
  `frontend/src/api/schema.d.ts` (regenerated), `docs/privacy.md`, `tests/test_robustness.py`.

## Resume commands
```
set -a; . ./.env; set +a
.venv/bin/pytest ziira/modules/jobs/tests -q
caffeinate -dimsu .venv/bin/pytest tests/test_jobs.py tests/test_jobs_intel.py tests/test_architecture.py tests/test_intel_plain.py -q --show-capture=no -p no:logging
.venv/bin/ruff check ziira/modules/jobs tests/test_jobs*.py tests/jobs_helpers.py; .venv/bin/mypy ziira; .venv/bin/lint-imports
```

